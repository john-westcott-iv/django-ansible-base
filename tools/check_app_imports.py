#!/usr/bin/env python3
"""
CI test to check that Django apps don't perform unwanted top-level imports of other Django apps.

This script analyzes Python files to detect top-level imports that could create tight coupling
between Django applications. It uses AST parsing to identify import statements and checks them
against configured rules.

Usage:
    python tools/check_app_imports.py [--config CONFIG_FILE] [--verbose]

Exit codes:
    0: No violations found
    1: Import violations detected
    2: Script error (missing files, invalid config, etc.)
"""

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class ImportViolation:
    """Represents an import violation."""

    def __init__(self, file_path: str, line_number: int, import_statement: str,
                 source_app: str, target_app: str, violation_type: str):
        self.file_path = file_path
        self.line_number = line_number
        self.import_statement = import_statement
        self.source_app = source_app
        self.target_app = target_app
        self.violation_type = violation_type

    def __str__(self):
        return (f"{self.file_path}:{self.line_number}: "
                f"{self.violation_type} - {self.source_app} -> {self.target_app}: "
                f"{self.import_statement}")


class ImportChecker:
    """Checks Python files for unwanted top-level imports between Django apps."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.violations: List[ImportViolation] = []
        self.django_apps = set(config.get('django_apps', []))
        self.app_base_path = config.get('app_base_path', '')
        self.allowed_imports = config.get('allowed_imports', {})
        self.prohibited_imports = config.get('prohibited_imports', {})
        self.ignore_patterns = config.get('ignore_patterns', [])

    def _get_app_name_from_path(self, file_path: str) -> Optional[str]:
        """Extract Django app name from file path."""
        path = Path(file_path)

        # Look for the app name in the path
        for part in path.parts:
            if part in self.django_apps:
                return part

        # If app_base_path is configured, try to extract from relative path
        if self.app_base_path:
            try:
                rel_path = path.relative_to(Path(self.app_base_path))
                if len(rel_path.parts) > 0 and rel_path.parts[0] in self.django_apps:
                    return rel_path.parts[0]
            except ValueError:
                pass

        return None

    def _extract_import_module(self, node: ast.AST) -> Optional[str]:
        """Extract the module name from an import node."""
        if isinstance(node, ast.Import):
            # Handle: import module
            if node.names:
                return node.names[0].name
        elif isinstance(node, ast.ImportFrom):
            # Handle: from module import ...
            return node.module
        return None

    def _get_target_app_from_import(self, import_module: str) -> Optional[str]:
        """Extract target Django app from import module name."""
        if not import_module:
            return None

        parts = import_module.split('.')

        # Check if any part of the import path matches a known Django app
        for part in parts:
            if part in self.django_apps:
                return part

        # Check for app_base_path patterns
        if self.app_base_path:
            base_name = Path(self.app_base_path).name
            if import_module.startswith(f"{base_name}."):
                # Extract app name after base path
                remaining = import_module[len(base_name) + 1:]
                if remaining and '.' in remaining:
                    potential_app = remaining.split('.')[0]
                    if potential_app in self.django_apps:
                        return potential_app
                elif remaining in self.django_apps:
                    return remaining

        return None

    def _is_import_allowed(self, source_app: str, target_app: str, import_module: str) -> bool:
        """Check if an import is explicitly allowed."""
        # Check specific allowed imports
        if source_app in self.allowed_imports:
            allowed = self.allowed_imports[source_app]
            if target_app in allowed or import_module in allowed:
                return True

        # Check global allowed imports
        if '*' in self.allowed_imports:
            allowed = self.allowed_imports['*']
            if target_app in allowed or import_module in allowed:
                return True

        return False

    def _is_import_prohibited(self, source_app: str, target_app: str, import_module: str) -> bool:
        """Check if an import is explicitly prohibited."""
        # Check specific prohibited imports
        if source_app in self.prohibited_imports:
            prohibited = self.prohibited_imports[source_app]
            if target_app in prohibited or import_module in prohibited:
                return True

        # Check global prohibited imports
        if '*' in self.prohibited_imports:
            prohibited = self.prohibited_imports['*']
            if target_app in prohibited or import_module in prohibited:
                return True

        return False

    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored based on patterns."""
        for pattern in self.ignore_patterns:
            if pattern in file_path:
                return True
        return False

    def _is_top_level_import(self, node: ast.AST, tree: ast.AST) -> bool:
        """Check if import is at module top-level (not inside function/class)."""
        # Find all parent nodes
        for parent_node in ast.walk(tree):
            for child in ast.iter_child_nodes(parent_node):
                if child == node:
                    # If direct parent is Module, it's top-level
                    if isinstance(parent_node, ast.Module):
                        return True
                    # If parent is a function or class, it's not top-level
                    if isinstance(parent_node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                              ast.ClassDef, ast.If, ast.Try, ast.With,
                                              ast.For, ast.While)):
                        return False
        return True

    def check_file(self, file_path: str) -> List[ImportViolation]:
        """Check a single Python file for import violations."""
        if self._should_ignore_file(file_path):
            return []

        source_app = self._get_app_name_from_path(file_path)
        if not source_app:
            return []  # Not in a Django app

        violations = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            tree = ast.parse(content, filename=file_path)

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    # Only check top-level imports
                    if not self._is_top_level_import(node, tree):
                        continue

                    import_module = self._extract_import_module(node)
                    if not import_module:
                        continue

                    target_app = self._get_target_app_from_import(import_module)
                    if not target_app or target_app == source_app:
                        continue  # No cross-app import or same app

                    # Check if this import is allowed
                    if self._is_import_allowed(source_app, target_app, import_module):
                        continue

                    # Check if this import is prohibited
                    violation_type = "PROHIBITED_IMPORT"
                    if self._is_import_prohibited(source_app, target_app, import_module):
                        violation_type = "EXPLICITLY_PROHIBITED"
                    elif not self.prohibited_imports:
                        # If no prohibited imports configured, treat all cross-app imports as violations
                        violation_type = "CROSS_APP_IMPORT"
                    else:
                        continue  # Not explicitly prohibited

                    # Create import statement string
                    if isinstance(node, ast.Import):
                        import_statement = f"import {import_module}"
                    else:
                        names = ", ".join([alias.name for alias in node.names])
                        import_statement = f"from {import_module} import {names}"

                    violation = ImportViolation(
                        file_path=file_path,
                        line_number=node.lineno,
                        import_statement=import_statement,
                        source_app=source_app,
                        target_app=target_app,
                        violation_type=violation_type
                    )
                    violations.append(violation)

        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)

        return violations

    def check_directory(self, directory: str) -> List[ImportViolation]:
        """Check all Python files in a directory recursively."""
        violations = []

        for root, dirs, files in os.walk(directory):
            # Skip common non-source directories
            dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache',
                                                   'node_modules', '.tox', 'venv', '.venv'}]

            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    violations.extend(self.check_file(file_path))

        return violations


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from file or return default config."""
    default_config = {
        "django_apps": [
            "authentication",
            "rbac",
            "resource_registry",
            "feature_flags",
            "preferences"
        ],
        "app_base_path": "ansible_base",
        "allowed_imports": {
            # Allow specific exceptions
            "authentication": ["rbac"],  # authentication can import from rbac
            "resource_registry": [],     # resource_registry should not import from other apps
        },
        "prohibited_imports": {
            # Explicitly prohibit certain imports
            "resource_registry": ["rbac"],  # resource_registry cannot import rbac at top level
        },
        "ignore_patterns": [
            "test",
            "migration",
            "__pycache__",
            ".pyc",
            "conftest.py"
        ]
    }

    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                user_config = json.load(f)
            # Merge with default config
            default_config.update(user_config)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading config file {config_path}: {e}", file=sys.stderr)
            return default_config

    return default_config


def main():
    parser = argparse.ArgumentParser(description="Check for unwanted top-level imports between Django apps")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--directory", "-d", default=".", help="Directory to check (default: current directory)")
    parser.add_argument("--output-format", choices=["text", "json"], default="text", help="Output format")

    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    if args.verbose:
        print(f"Checking directory: {args.directory}")
        print(f"Django apps: {', '.join(config['django_apps'])}")
        print(f"App base path: {config['app_base_path']}")
        print()

    # Initialize checker and run
    checker = ImportChecker(config)
    violations = checker.check_directory(args.directory)

    if not violations:
        if args.verbose:
            print("✅ No import violations found!")
        return 0

    # Output violations
    if args.output_format == "json":
        violation_data = []
        for violation in violations:
            violation_data.append({
                "file": violation.file_path,
                "line": violation.line_number,
                "import": violation.import_statement,
                "source_app": violation.source_app,
                "target_app": violation.target_app,
                "type": violation.violation_type
            })
        print(json.dumps({"violations": violation_data}, indent=2))
    else:
        print(f"❌ Found {len(violations)} import violation(s):")
        print()
        for violation in violations:
            print(f"  {violation}")
        print()
        print("These violations indicate tight coupling between Django apps.")
        print("Consider using conditional imports or dependency injection instead.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
