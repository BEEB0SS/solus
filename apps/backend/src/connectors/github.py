"""
Solus GitHub / local repo connector.
Walks a local repo, classifies files, builds entities and relations.
Supports both local paths and GitHub URLs (clones to ~/.solus/repos/).
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'packages', 'shared-types', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Entity, Relation, EntityType, RelationType, SourceType

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'build', 'devel', '.venv', 'dist'}
CODE_EXTENSIONS = {'.py', '.cpp', '.c', '.h', '.ino', '.launch', '.urdf', '.xacro',
                   '.yaml', '.yml', '.json', '.msg', '.srv', '.cfg'}

REPOS_DIR = os.path.join(os.path.expanduser("~"), ".solus", "repos")


class GitHubConnector:
    def __init__(self, url_or_path: str, project_id: str):
        self.project_id = project_id
        self.repo_path = self._resolve_path(url_or_path)

    def _resolve_path(self, url_or_path: str) -> str:
        # If it looks like a URL, clone or pull
        if url_or_path.startswith("http://") or url_or_path.startswith("https://") or url_or_path.startswith("git@"):
            repo_name = url_or_path.rstrip("/").split("/")[-1].removesuffix(".git")
            local_path = os.path.join(REPOS_DIR, repo_name)
            os.makedirs(REPOS_DIR, exist_ok=True)

            if os.path.isdir(os.path.join(local_path, ".git")):
                # Already cloned — pull latest
                print(f"[github] pulling {repo_name}")
                subprocess.run(["git", "-C", local_path, "pull", "--ff-only"],
                               capture_output=True, timeout=60)
            else:
                # Fresh clone
                print(f"[github] cloning {url_or_path} → {local_path}")
                subprocess.run(["git", "clone", url_or_path, local_path],
                               capture_output=True, timeout=120)
            return local_path

        # Local path
        return os.path.abspath(url_or_path)

    def ingest(self) -> dict:
        items = []
        entities = []
        relations = []
        dir_files: dict[str, list[Entity]] = {}

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in CODE_EXTENSIONS:
                    continue

                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, self.repo_path)
                entity_type, metadata = self._classify(fname, ext)

                # Read small .ino / .py files
                if ext in ('.ino', '.py'):
                    content = self.extract_file_content(rel_path, max_chars=8000)
                    if content is not None:
                        metadata["file_content"] = content

                ent = Entity(
                    project_id=self.project_id,
                    entity_type=entity_type,
                    name=fname,
                    source=SourceType.GITHUB,
                    source_ref=rel_path,
                    metadata=metadata,
                )
                entities.append(ent)

                items.append({
                    "ref": rel_path,
                    "name": fname,
                    "entity_type": entity_type.value,
                    "metadata": metadata,
                })

                parent = os.path.dirname(rel_path)
                dir_files.setdefault(parent, []).append(ent)

        # Detect ROS packages
        ros_packages: dict[str, list[Entity]] = {}
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            if 'package.xml' in files:
                pkg_name = os.path.basename(root)
                pkg_rel = os.path.relpath(root, self.repo_path)
                ros_packages[pkg_rel] = []
                for ent in entities:
                    if ent.source_ref.startswith(pkg_rel + os.sep) or ent.source_ref.startswith(pkg_rel + '/'):
                        ros_packages[pkg_rel].append(ent)
                        ent.metadata["ros_package"] = pkg_name

        # Build depends_on relations for files in the same directory
        for dirpath, ents in dir_files.items():
            if len(ents) < 2:
                continue
            for i in range(1, len(ents)):
                rel = Relation(
                    project_id=self.project_id,
                    source_entity_id=ents[i].id,
                    target_entity_id=ents[0].id,
                    relation_type=RelationType.DEPENDS_ON,
                    metadata={"reason": "same_directory"},
                )
                relations.append(rel)

        return {"items": items, "entities": entities, "relations": relations}

    def extract_file_content(self, rel_path: str, max_chars: int = 8000) -> str | None:
        full = os.path.join(self.repo_path, rel_path)
        try:
            size = os.path.getsize(full)
            if size > 10 * 1024:
                return None
            with open(full, 'r', errors='replace') as f:
                return f.read(max_chars)
        except (OSError, IOError):
            return None

    def _classify(self, filename: str, ext: str) -> tuple[EntityType, dict]:
        metadata: dict = {}
        if ext == '.ino':
            return EntityType.SOFTWARE_MODULE, {"category": "arduino_sketch"}
        elif ext in ('.urdf', '.xacro'):
            return EntityType.SIMULATION_ASSET, {}
        elif ext == '.launch':
            return EntityType.SOFTWARE_MODULE, {"category": "launch_file"}
        elif ext in ('.msg', '.srv'):
            return EntityType.INTERFACE, {}
        elif ext in ('.yaml', '.yml', '.json', '.cfg'):
            return EntityType.DOCUMENT, {"category": "config"}
        else:
            return EntityType.SOFTWARE_MODULE, {}
