#!/usr/bin/env python3
"""Render a tolerant mermaid task graph to DOT, PNG, and SVG with local graphviz.

The canonical input is docs/task_dependencies.mmd, a standalone mermaid graph
whose nodes carry one of seven :::status tags and whose edges use -->, -.->,
or ==>. The renderer maps that readable structure onto the visual layer, a
theme file (the skill's theme.default.json merged with an optional project
override at docs/task_dependencies.theme.json), writes a DOT file next to the
input, and renders a 150 DPI PNG plus an SVG with the local graphviz dot.
Nothing is uploaded to an external renderer, and mmdc is not used.

Usage:
  render.py [--theme THEME] [mmd-file]

Arguments:
  mmd-file    Mermaid graph to render (default: docs/task_dependencies.mmd).
  --theme     Theme JSON merged over the built-in default (default: the
              <stem>.theme.json next to the mmd if present, else the skill's
              theme.default.json).
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MMD = "docs/task_dependencies.mmd"
SKILL_DEFAULT_THEME = Path(__file__).resolve().parent.parent / "theme.default.json"

STATUS_TAGS = ("actionable", "in-flight", "goal", "pending", "done",
               "recurring", "blocked")
DIRECTIONS = ("TB", "TD", "BT", "LR", "RL")
DIAGRAM_KEYWORDS = (
    "sequenceDiagram", "classDiagram", "stateDiagram", "stateDiagram-v2",
    "erDiagram", "gantt", "pie", "journey", "mindmap", "timeline",
    "quadrantChart", "xychart-beta", "sankey-beta", "block-beta",
    "packet-beta", "kanban", "gitGraph", "requirementDiagram",
)

ID_RE = re.compile(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]*|"(?:[^"\\]|\\.)*")')
TAG_RE = re.compile(r":::\s*([A-Za-z0-9_-]+)")

# (opener, closer, dot shape, rounded corners)
TWO_CHAR_SHAPES = (
    ("[[", "]]", "box", False),
    ("((", "))", "doublecircle", False),
    ("{{", "}}", "hexagon", False),
    ("([", "])", "box", True),
    ("[(", ")]", "cylinder", False),
)
SINGLE_CHAR_SHAPES = (
    ("[", "]", "box", False),
    ("(", ")", "box", True),
    ("{", "}", "diamond", False),
    (">", "]", "box", False),
)

# Edge operators with optional labels. Labeled forms come before the plain
# forms they start with, so '-->|x|' is not read as a bare '-->'.
EDGE_OPS = (
    (re.compile(r"-->\|(.*?)\|"), "hard"),
    (re.compile(r"--\s+(.*?)\s+-->"), "hard"),
    (re.compile(r"-\.->\|(.*?)\|"), "soft"),
    (re.compile(r"-\.\s+(.*?)\s+\.->"), "soft"),
    (re.compile(r"==>\|(.*?)\|"), "supervision"),
    (re.compile(r"==\s+(.*?)\s+==>"), "supervision"),
    (re.compile(r"-->"), "hard"),
    (re.compile(r"-\.->"), "soft"),
    (re.compile(r"==>"), "supervision"),
)

GRAPH_HEADER_RE = re.compile(r"(?:graph|flowchart)(?:\s+([A-Za-z]+))?\s*$")
DIRECTION_RE = re.compile(r"direction\s+[A-Za-z]+\s*$")


class RenderError(Exception):
    """A parse or render failure, with the source line it came from."""

    def __init__(self, lineno, message):
        super().__init__(message)
        self.lineno = lineno
        self.message = message


class NotANodeError(Exception):
    """The statement started like a node but has non-node text left over."""


class Node:
    def __init__(self, node_id, label, shape, rounded, status, cluster=None):
        self.node_id = node_id
        self.label = label if label is not None else node_id
        self.shape = shape
        self.rounded = rounded
        self.status = status or "default"
        self.cluster = cluster
        self.order = None


class Cluster:
    def __init__(self, source_id, dot_id, title, lineno):
        self.source_id = source_id
        self.dot_id = dot_id
        self.title = title
        self.lineno = lineno
        self.nodes = []


class Graph:
    def __init__(self):
        self.title = None
        self.clusters = []
        self.cluster_ids = {}
        self.nodes = {}
        self.edges = []  # (src_id, dst_id, kind, label)
        self._node_order = 0


# ----------------------------------------------------------------------
# Line-oriented tolerant parser
# ----------------------------------------------------------------------

def skip_spaces(text, pos):
    while pos < len(text) and text[pos] in " \t":
        pos += 1
    return pos


def parse_id(text, pos, lineno):
    match = ID_RE.match(text, pos)
    if not match:
        if pos >= len(text):
            raise RenderError(lineno, "expected a node id but the statement ended")
        raise RenderError(
            lineno,
            f"expected a node id but found {text[pos:].strip()[:24]!r}")
    raw = match.group(0)
    if raw.startswith('"'):
        raw = raw[1:-1].replace('\\"', '"')
    return raw, match.end()


def check_plain_label(label, lineno):
    stripped = label.strip()
    if stripped.startswith("<") and ">" in stripped:
        raise RenderError(
            lineno,
            f"HTML labels are not supported (found {label[:24]!r}); "
            "use plain text labels")


def parse_shape(text, pos, lineno):
    """Parse an optional shape suffix after a node id.

    Returns (label, dot shape, rounded, new position).
    """
    if pos >= len(text):
        return None, None, False, pos
    if text.startswith("[/", pos) or text.startswith("[\\", pos):
        opener = text[pos:pos + 2]
        closer_match = re.compile(r"/\]|\\\]").search(text, pos + 2)
        if not closer_match:
            raise RenderError(
                lineno,
                f"unterminated shape {opener!r} (expected a closing '/]' or '\\]')")
        closer = closer_match.group(0)
        label = text[pos + 2:closer_match.start()]
        if opener == "[/" and closer == "/]":
            shape = "parallelogram"
        elif opener == "[\\" and closer == "\\]":
            shape = "parallelogram"
        elif opener == "[/":
            shape = "trapezium"
        else:
            shape = "invtrapezium"
        return label, shape, False, closer_match.end()
    for opener, closer, shape, rounded in TWO_CHAR_SHAPES:
        if text.startswith(opener, pos):
            end = text.find(closer, pos + 2)
            if end < 0:
                raise RenderError(
                    lineno,
                    f"unterminated shape {opener!r} (expected {closer!r})")
            return text[pos + 2:end], shape, rounded, end + 2
    for opener, closer, shape, rounded in SINGLE_CHAR_SHAPES:
        if text[pos] == opener:
            end = text.find(closer, pos + 1)
            if end < 0:
                raise RenderError(
                    lineno,
                    f"unterminated shape {opener!r} (expected {closer!r})")
            return text[pos + 1:end], shape, rounded, end + 1
    return None, None, False, pos


def parse_status_tag(text, pos, lineno):
    match = TAG_RE.match(text, pos)
    if not match:
        return None, pos
    tag = match.group(1)
    if tag not in STATUS_TAGS:
        raise RenderError(
            lineno,
            f"unknown status tag {tag!r} "
            f"(expected one of: {', '.join(STATUS_TAGS)})")
    return tag, match.end()


def parse_node_statement(text, lineno):
    node_id, pos = parse_id(text, 0, lineno)
    label, shape, rounded, pos = parse_shape(text, pos, lineno)
    tag, pos = parse_status_tag(text, pos, lineno)
    if text[pos:].strip():
        raise NotANodeError()
    if label is not None:
        check_plain_label(label, lineno)
    return node_id, label, shape, rounded, tag


def parse_endpoint(text, pos, lineno):
    pos = skip_spaces(text, pos)
    node_id, pos = parse_id(text, pos, lineno)
    label, shape, rounded, pos = parse_shape(text, pos, lineno)
    tag, pos = parse_status_tag(text, pos, lineno)
    if label is not None:
        check_plain_label(label, lineno)
    return (node_id, label, shape, rounded, tag), pos


def match_edge_op(text, pos, lineno):
    """Match an edge operator at pos. Returns (kind, label, new pos)."""
    for regex, kind in EDGE_OPS:
        match = regex.match(text, pos)
        if match:
            label = match.group(1).strip() if match.lastindex else None
            if label:
                check_plain_label(label, lineno)
            return kind, (label or None), match.end()
    rest = text[pos:]
    if rest.startswith("--o") or rest.startswith("--x"):
        raise RenderError(lineno, "open arrowheads (--o, --x) are not supported")
    if rest.startswith("---") or rest.startswith("--"):
        raise RenderError(
            lineno, "undirected edges (---) are not supported; use -->, -.->, or ==>")
    if rest.startswith("-."):
        raise RenderError(
            lineno, f"unsupported edge syntax {rest.strip()[:20]!r}; use -.->")
    if rest.startswith("=="):
        raise RenderError(
            lineno, f"unsupported edge syntax {rest.strip()[:20]!r}; use ==>")
    return None, None, pos


def parse_edge_chain(text, lineno):
    """Parse a chain like 'A & B -->|label| C --> D' into edge tuples."""
    first, pos = parse_endpoint(text, 0, lineno)
    left = [first]
    pending_kind = None
    pending_label = None
    prev = None
    edges = []
    while True:
        pos = skip_spaces(text, pos)
        if pos >= len(text):
            break
        if text[pos] == "&":
            endpoint, pos = parse_endpoint(text, pos + 1, lineno)
            left.append(endpoint)
            continue
        kind, label, pos = match_edge_op(text, pos, lineno)
        if kind is None:
            raise RenderError(
                lineno,
                "could not parse statement (neither a node statement nor an "
                f"edge chain): {text.strip()!r}")
        if pending_kind is not None:
            for source in prev:
                for target in left:
                    edges.append((source, target, pending_kind, pending_label))
        pending_kind, pending_label = kind, label
        prev = left
        endpoint, pos = parse_endpoint(text, pos, lineno)
        left = [endpoint]
    if pending_kind is not None:
        for source in prev:
            for target in left:
                edges.append((source, target, pending_kind, pending_label))
    if not edges:
        raise RenderError(lineno, f"no edge found in statement {text.strip()!r}")
    return edges


def parse_subgraph(graph, stack, stripped, lineno):
    rest = stripped[len("subgraph"):].strip()
    if not rest:
        raise RenderError(lineno, "subgraph needs an id or a title")
    source_id = None
    title = None
    if rest.startswith('"'):
        match = re.match(r'"((?:[^"\\]|\\.)*)"\s*(.*)$', rest)
        if not match:
            raise RenderError(lineno, f"unterminated subgraph title in {stripped!r}")
        title = match.group(1).replace('\\"', '"')
        remainder = match.group(2).strip()
        if remainder and not DIRECTION_RE.match(remainder):
            raise RenderError(
                lineno, f"unexpected text after subgraph title: {remainder!r}")
    else:
        match = ID_RE.match(rest)
        if not match:
            raise RenderError(lineno, f"could not parse subgraph id in {stripped!r}")
        raw_id = match.group(0)
        source_id = raw_id[1:-1].replace('\\"', '"') if raw_id.startswith('"') else raw_id
        pos = match.end()
        pos = skip_spaces(rest, pos)
        if pos < len(rest) and rest[pos] in "[(":
            closer = "]" if rest[pos] == "[" else ")"
            end = rest.find(closer, pos + 1)
            if end < 0:
                raise RenderError(lineno, f"unterminated subgraph title in {stripped!r}")
            title = rest[pos + 1:end].strip()
            if len(title) >= 2 and title[0] == '"' and title[-1] == '"':
                title = title[1:-1].replace('\\"', '"')
            pos = end + 1
        remainder = rest[pos:].strip()
        if remainder and not DIRECTION_RE.match(remainder):
            raise RenderError(
                lineno, f"unexpected text after subgraph: {remainder!r}")
    if source_id is not None and source_id in graph.cluster_ids:
        raise RenderError(lineno, f"duplicate subgraph id {source_id!r}")
    dot_id = make_cluster_id(graph, source_id)
    cluster = Cluster(source_id, dot_id, title, lineno)
    graph.clusters.append(cluster)
    if source_id is not None:
        graph.cluster_ids[source_id] = cluster
    stack.append(cluster)


def make_cluster_id(graph, source_id):
    base = "cluster_" + re.sub(
        r"[^A-Za-z0-9_]", "_", source_id or f"subgraph{len(graph.clusters) + 1}")
    dot_id = base
    counter = 2
    while any(c.dot_id == dot_id for c in graph.clusters):
        dot_id = f"{base}_{counter}"
        counter += 1
    return dot_id


def register_node(graph, stack, endpoint, lineno):
    node_id, label, shape, rounded, tag = endpoint
    node = graph.nodes.get(node_id)
    if node is None:
        cluster = stack[-1] if stack else None
        node = Node(node_id, label, shape, rounded, tag, cluster)
        node.order = graph._node_order
        graph._node_order += 1
        graph.nodes[node_id] = node
        if cluster is not None:
            cluster.nodes.append(node)
    elif node.status == "default" and tag:
        node.status = tag
    return node


def resolve_endpoint(graph, stack, endpoint, lineno):
    """Map an edge endpoint to a node, or None when it names a subgraph."""
    node_id = endpoint[0]
    if node_id in graph.cluster_ids:
        return None
    return register_node(graph, stack, endpoint, lineno)


def handle_statement(graph, stack, stripped, lineno):
    match = GRAPH_HEADER_RE.match(stripped)
    if match:
        direction = match.group(1)
        if direction and direction.upper() not in DIRECTIONS:
            raise RenderError(
                lineno,
                f"unknown graph direction {direction!r} "
                "(expected TB, TD, BT, LR, or RL)")
        return
    if DIRECTION_RE.match(stripped):
        return  # subgraph direction lines: house style forces rankdir TB
    if stripped == "end":
        if not stack:
            raise RenderError(lineno, "'end' without a matching subgraph")
        stack.pop()
        return
    if stripped.startswith("subgraph"):
        parse_subgraph(graph, stack, stripped, lineno)
        return
    for keyword in DIAGRAM_KEYWORDS:
        if stripped.startswith(keyword):
            raise RenderError(
                lineno,
                f"{keyword} diagrams are not supported; this renderer handles "
                "a graph/flowchart of nodes and edges")
    if stripped.startswith("classDef"):
        raise RenderError(
            lineno,
            "classDef styling is not supported; the theme file owns colors "
            "and line styles")
    if stripped.startswith("class "):
        raise RenderError(
            lineno,
            "class statements are not supported; attach the status to the "
            "node as id:::status")
    if stripped.startswith("style"):
        raise RenderError(
            lineno,
            "style statements are not supported; put visual mapping in the "
            "theme file")
    if stripped.startswith("linkStyle"):
        raise RenderError(
            lineno,
            "linkStyle statements are not supported; edge styling lives in "
            "the theme file")
    if stripped.startswith("click"):
        raise RenderError(lineno, "click handlers are not supported")
    try:
        parts = parse_node_statement(stripped, lineno)
    except NotANodeError:
        parts = None
    if parts is not None:
        register_node(graph, stack, parts, lineno)
        return
    edges = parse_edge_chain(stripped, lineno)
    for source, target, kind, label in edges:
        resolve_endpoint(graph, stack, source, lineno)
        resolve_endpoint(graph, stack, target, lineno)
        graph.edges.append((source[0], target[0], kind, label))


def parse_mermaid(source):
    graph = Graph()
    stack = []
    lines = source.lstrip("\ufeff").splitlines()
    for lineno, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%{"):
            continue  # mermaid init directives: the theme file owns config
        if stripped.startswith("%%"):
            if graph.title is None:
                comment = stripped[2:].strip()
                if comment:
                    graph.title = comment
            continue
        stripped = stripped.rstrip(";").strip()
        if not stripped:
            continue
        handle_statement(graph, stack, stripped, lineno)
    if stack:
        raise RenderError(
            stack[-1].lineno,
            f"unclosed subgraph {stack[-1].source_id or stack[-1].title!r}")
    return graph


# ----------------------------------------------------------------------
# Theme and DOT emission
# ----------------------------------------------------------------------

def deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value


def load_theme(mmd_path, theme_arg):
    try:
        default = json.loads(SKILL_DEFAULT_THEME.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(
            0, f"cannot load the skill default theme {SKILL_DEFAULT_THEME}: {exc}")
    override_path = None
    if theme_arg:
        override_path = Path(theme_arg)
    else:
        candidate = mmd_path.with_suffix(".theme.json")
        if candidate.is_file():
            override_path = candidate
    if override_path is not None:
        if not override_path.is_file():
            raise RenderError(0, f"theme file not found: {override_path}")
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RenderError(0, f"cannot load theme {override_path}: {exc}")
        deep_merge(default, override)
    return default


def dot_string(text):
    """Escape a string for a quoted DOT value, keeping literal \n escapes."""
    parts = []
    for chunk in str(text).split("\\n"):
        chunk = chunk.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(chunk)
    return "\\n".join(parts)


def dot_id(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", str(text))


def html_escape(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def build_legend_label(theme):
    legend = theme.get("legend", {})
    title = legend.get("title", "Legend")
    background = legend.get("background", "#eeeeee")
    rows = [f'<tr><td colspan="2" bgcolor="{html_escape(background)}">'
            f"<b>{html_escape(title)}</b></td></tr>"]
    for entry in legend.get("nodes", []):
        color = entry.get("color", "#ffffff")
        text = entry.get("text", "")
        rows.append(f'<tr><td bgcolor="{html_escape(color)}" width="20"> </td>'
                    f'<td align="left">{html_escape(text)}</td></tr>')
    edge_heading = legend.get("edge_heading")
    for entry in legend.get("edges", []):
        if edge_heading:
            rows.append(f'<tr><td colspan="2" bgcolor="{html_escape(background)}">'
                        f"<b>{html_escape(edge_heading)}</b></td></tr>")
            edge_heading = None
        style = entry.get("style", "solid")
        text = entry.get("text", "")
        rows.append(f'<tr><td align="left" bgcolor="#ffffff">'
                    f"<b>{html_escape(style)}</b></td>"
                    f'<td align="left">{html_escape(text)}</td></tr>')
    return ('<<table border="0" cellborder="1" cellspacing="0" cellpadding="4">'
            + "".join(rows) + "</table>>")


def node_attributes(node, theme):
    node_theme = theme.get("nodes", {})
    spec = node_theme.get(node.status) or node_theme.get("default") or {}
    fill = spec.get("fill", "#ffffff")
    stroke = spec.get("stroke", "#333333")
    outline = spec.get("outline", "solid")
    if node.status == "goal":
        shape = spec.get("shape") or "octagon"
    elif node.shape:
        shape = node.shape
    else:
        shape = spec.get("shape", "box")
    style = "filled"
    if node.rounded:
        style += ",rounded"
    if outline != "solid":
        style += f",{outline}"
    attrs = [
        f'label="{dot_string(node.label)}"',
        f"shape={shape}",
        f'style="{style}"',
        f'fillcolor="{fill}"',
        f'color="{stroke}"',
    ]
    return "[" + ", ".join(attrs) + "]"


def edge_attributes(kind, label, theme):
    spec = theme.get("edges", {}).get(kind, {}) or {}
    style = spec.get("style", "solid")
    color = spec.get("color", "#666666")
    attrs = [f"style={style}", f'color="{color}"']
    if label:
        attrs.append(f'label="{dot_string(label)}"')
    return "[" + ", ".join(attrs) + "]"


def cluster_top_node(graph, cluster):
    """Pick the cluster node the invisible legend anchor should reach."""
    if not cluster.nodes:
        return None
    incoming = {dst_id for _, dst_id, _, _ in graph.edges}
    for node in cluster.nodes:
        if node.node_id not in incoming:
            return node
    return cluster.nodes[0]


def emit_dot(graph, theme, name):
    g = theme.get("graph", {})
    out = []
    out.append(f"digraph {dot_id(name)} {{")
    out.append(f'    rankdir="{g.get("rankdir", "TB")}";')
    out.append("    compound=true;")
    if graph.title:
        out.append(f'    label="{dot_string(graph.title)}";')
        out.append('    labelloc="t";')
    out.append(f'    fontsize={g.get("label_fontsize", 20)};')
    out.append(f'    node [fontsize={g.get("node_fontsize", 14)}];')
    out.append(f'    edge [fontsize={g.get("edge_fontsize", 12)}];')
    out.append("    {")
    out.append("        rank=source;")
    out.append(f"        legend [shape=plaintext, margin=0, "
               f"label={build_legend_label(theme)}];")
    out.append("    }")
    for cluster in graph.clusters:
        out.append(f'    subgraph "{cluster.dot_id}" {{')
        if cluster.title:
            out.append(f'        label="{dot_string(cluster.title)}";')
        out.append(f'        fontsize={g.get("cluster_fontsize", 14)};')
        cluster_style = g.get("cluster_style")
        if cluster_style:
            out.append(f'        style="{cluster_style}";')
        for node in cluster.nodes:
            out.append(f'        "{node.node_id}" {node_attributes(node, theme)};')
        out.append("    }")
    for node in sorted(graph.nodes.values(), key=lambda n: n.order):
        if node.cluster is None:
            out.append(f'    "{node.node_id}" {node_attributes(node, theme)};')
    weight = theme.get("dot", {}).get("anchor_weight", 100)
    for cluster in graph.clusters:
        top = cluster_top_node(graph, cluster)
        if top is not None:
            out.append(f'    "legend" -> "{top.node_id}" [style=invis, '
                       f"weight={weight}];")
    for src_id, dst_id, kind, label in graph.edges:
        src_cluster = graph.cluster_ids.get(src_id)
        dst_cluster = graph.cluster_ids.get(dst_id)
        src_dot = src_cluster.dot_id if src_cluster else src_id
        dst_dot = dst_cluster.dot_id if dst_cluster else dst_id
        out.append(f'    "{src_dot}" -> "{dst_dot}" '
                   f"{edge_attributes(kind, label, theme)};")
    out.append("}")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def render_with_dot(dot_path, png_path, svg_path):
    for render_args, out_path, label in (
        (["dot", "-Tpng", "-Gdpi=150", str(dot_path), "-o", str(png_path)],
         png_path, "PNG"),
        (["dot", "-Tsvg", str(dot_path), "-o", str(svg_path)], svg_path, "SVG"),
    ):
        proc = subprocess.run(render_args, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RenderError(
                0, f"graphviz dot failed while rendering the {label}: {detail}")
        if not out_path.is_file() or out_path.stat().st_size == 0:
            raise RenderError(
                0, f"graphviz dot produced no {label} output at {out_path}")


def main(argv):
    parser = argparse.ArgumentParser(
        prog="render.py",
        description="Render a mermaid task graph to DOT, PNG, and SVG with "
                    "local graphviz.")
    parser.add_argument(
        "mmd_file", nargs="?", default=DEFAULT_MMD,
        help=f"mermaid graph to render (default: {DEFAULT_MMD})")
    parser.add_argument(
        "--theme", metavar="THEME",
        help="theme JSON merged over the built-in default (default: the "
             ".theme.json next to the mmd if present, else the skill default)")
    args = parser.parse_args(argv)

    mmd_path = Path(args.mmd_file)
    if not mmd_path.is_file():
        print(f"error: mermaid file not found: {mmd_path}", file=sys.stderr)
        return 1
    if shutil.which("dot") is None:
        print("error: graphviz 'dot' was not found on PATH; render.py needs "
              "the local dot binary (mmdc is not used)", file=sys.stderr)
        return 1
    try:
        source = mmd_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {mmd_path}: {exc}", file=sys.stderr)
        return 1
    try:
        theme = load_theme(mmd_path, args.theme)
        graph = parse_mermaid(source)
        dot_source = emit_dot(graph, theme, mmd_path.stem)
    except RenderError as exc:
        if exc.lineno:
            print(f"error: {mmd_path}: line {exc.lineno}: {exc.message}",
                  file=sys.stderr)
        else:
            print(f"error: {exc.message}", file=sys.stderr)
        return 1

    dot_path = mmd_path.with_suffix(".dot")
    png_path = mmd_path.with_suffix(".png")
    svg_path = mmd_path.with_suffix(".svg")
    try:
        dot_path.write_text(dot_source, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write {dot_path}: {exc}", file=sys.stderr)
        return 1
    try:
        render_with_dot(dot_path, png_path, svg_path)
    except RenderError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1
    for out_path in (dot_path, png_path, svg_path):
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
