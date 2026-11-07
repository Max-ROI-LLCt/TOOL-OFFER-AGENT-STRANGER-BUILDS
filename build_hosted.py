"""Build flat Python modules for Agentverse without copying private local files."""

from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parent
MODULES = ("customer_recovery", "guided_cards", "parcel_fixture", "restrictions", "export_delivery", "chat", "documents", "drafting", "fahce", "fahce_checkout", "storage", "workflow", "owner_export", "commerce", "protocol_payment", "cloudflare_custody", "conversation", "listing_guidance", "buyer_guidance", "model_runtime", "offer_representation", "machine", "machine_contract", "product_policy", "readiness", "readiness_cards")


def validate_import_graph(sources):
    """Agentverse rejects static local cycles, including imports inside functions."""
    modules = {Path(name).stem: source for name, source in sources.items()}
    graph = {}
    for name, source in modules.items():
        dependencies = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                dependencies.update(alias.name.split(".")[0] for alias in node.names)
        graph[name] = dependencies & modules.keys()
    visited = set()

    def visit(name, path):
        if name in path:
            raise ValueError("Agentverse rejects circular local imports: " + " -> ".join(path + [name]))
        if name in visited:
            return
        for dependency in sorted(graph[name]):
            visit(dependency, path + [name])
        visited.add(name)

    for name in sorted(graph):
        visit(name, [])


def build(destination=None, *, modules=None):
    selected = MODULES if modules is None else tuple(modules)
    if not selected or any(name not in MODULES for name in selected):
        raise ValueError("Choose one or more known hosted modules.")
    destination = Path(destination) if destination else ROOT / "hosted_build"
    destination.mkdir(parents=True, exist_ok=True)
    for name in selected:
        source = (ROOT / "tool_offer_agent" / (name + ".py")).read_text(encoding="utf-8")
        source = re.sub(r"(?m)^(\s*)from \.([a-z_]+) import ", r"\1from \2 import ", source)
        compile(source, name + ".py", "exec")
        (destination / (name + ".py")).write_text(source, encoding="utf-8")
    if modules is not None:
        return destination
    (destination / "agent.py").write_text(
        '"""Generated Agentverse entrypoint; edit the local package and rebuild."""\n'
        'from chat import create_agent\n\n'
        'agent = create_agent(hosted=True)\n\n'
        'if __name__ == "__main__":\n    agent.run()\n',
        encoding="utf-8",
    )
    (destination / "cli.py").write_text(
        '"""CLI runs locally only; hosted conversations use agent.py."""\n', encoding="utf-8"
    )
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modules", nargs="+", choices=MODULES,
                        help="Regenerate only these modules; preserve other files and entrypoints.")
    print(build(modules=parser.parse_args().modules))
