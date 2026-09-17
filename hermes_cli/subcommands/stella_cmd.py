"""Stella CLI command dispatcher.

Exposes CLI management for:
- Stella nested profiles (profiles/<id>/ with profile.json metadata)
- One-click Hermes -> Stella migration engine
"""

import argparse
import json
import sys
from pathlib import Path

from stella.constants import (
    DEFAULT_PRIMARY_PROFILE_ID,
    SUPPORTED_MIGRATION_COMPONENTS,
)
from stella.migration import HermesMigrationEngine
from stella.profiles import StellaProfileManager


def build_stella_parser(subparsers):
    """Register 'hermes stella' command tree."""
    parser = subparsers.add_parser(
        "stella",
        help="Manage Stella nested profiles and Hermes migration.",
        description="Stella architecture tools: nested profile isolation and safe Hermes import.",
    )
    stella_subs = parser.add_subparsers(dest="stella_subcommand")

    # --- Profile Subgroup ---
    prof_parser = stella_subs.add_parser("profile", help="Manage Stella nested profiles")
    prof_subs = prof_parser.add_subparsers(dest="stella_profile_action")

    # stella profile list
    prof_subs.add_parser("list", help="List all Stella nested profiles")

    # stella profile create <name>
    create_p = prof_subs.add_parser("create", help="Create a new nested profile")
    create_p.add_argument("name", help="Display name for the profile")
    create_p.add_argument("--id", dest="profile_id", help="Explicit profile ID (optional)")
    create_p.add_argument("--desc", default="", help="Profile description")
    create_p.add_argument("--primary", action="store_true", help="Set as primary profile")

    # stella profile rename <id> <new_name>
    rename_p = prof_subs.add_parser("rename", help="Change profile display name")
    rename_p.add_argument("id", help="Internal profile ID")
    rename_p.add_argument("new_name", help="New user-facing display name")

    # stella profile delete <id>
    del_p = prof_subs.add_parser("delete", help="Delete a profile")
    del_p.add_argument("id", help="Profile ID to delete")
    del_p.add_argument("--force", action="store_true", help="Allow deleting primary profile")
    del_p.add_argument("--purge", action="store_true", help="Completely remove instead of archiving")

    # --- Migration Subgroup ---
    mig_parser = stella_subs.add_parser("migrate", help="Hermes to Stella migration tools")
    mig_subs = mig_parser.add_subparsers(dest="stella_migrate_action")

    # stella migrate detect
    mig_subs.add_parser("detect", help="Scan host system for existing Hermes installations")

    # stella migrate preview [source]
    prev_p = mig_subs.add_parser("preview", help="Preview migratable components (dry run)")
    prev_p.add_argument("source", nargs="?", default=None, help="Hermes root path (optional auto-detect)")
    prev_p.add_argument("--target", default=DEFAULT_PRIMARY_PROFILE_ID, help="Target profile ID")
    prev_p.add_argument(
        "--component",
        dest="components",
        action="append",
        choices=sorted(SUPPORTED_MIGRATION_COMPONENTS),
        help="Component to preview (repeat to select more; omit for safe defaults)",
    )

    # stella migrate run [source]
    run_p = mig_subs.add_parser("run", help="Execute safe selective migration from Hermes")
    run_p.add_argument("source", nargs="?", default=None, help="Hermes root path (optional auto-detect)")
    run_p.add_argument("--target", default=DEFAULT_PRIMARY_PROFILE_ID, help="Target profile ID")
    run_p.add_argument(
        "--component",
        dest="components",
        action="append",
        choices=sorted(SUPPORTED_MIGRATION_COMPONENTS),
        help="Component to migrate (repeat to select more; omit for safe defaults)",
    )
    run_p.add_argument("--overwrite", action="store_true", help="Overwrite conflicting target files")
    run_p.add_argument("--include-profiles", action="store_true", help="Also import named sub-profiles")

    # stella migrate rollback [target]
    rb_p = mig_subs.add_parser("rollback", help="Roll back a previous migration")
    rb_p.add_argument("--target", default=DEFAULT_PRIMARY_PROFILE_ID, help="Target profile ID")

    parser.set_defaults(func=cmd_stella)
    return parser


def cmd_stella(args):
    """Dispatch 'hermes stella' commands."""
    sub = getattr(args, "stella_subcommand", None)
    if not sub:
        print("Usage: hermes stella [profile|migrate] ...")
        return 1

    if sub == "profile":
        return _handle_profile_cmd(args)
    if sub == "migrate":
        return _handle_migrate_cmd(args)

    print(f"Unknown stella subcommand: {sub}")
    return 1


def _handle_profile_cmd(args):
    action = getattr(args, "stella_profile_action", None)
    mgr = StellaProfileManager()
    mgr.ensure_root_layout(auto_create_default=True)

    if action in (None, "list"):
        profiles = mgr.list_profiles()
        print(f"\nStella Profiles ({len(profiles)} found in {mgr.profiles_dir}):")
        for p in profiles:
            star = " ★ [PRIMARY]" if p.is_primary else ""
            print(f"  • {p.display_name} (ID: {p.id}){star}")
            if p.description:
                print(f"    Description: {p.description}")
            print(f"    Path: {p.path}")
        print()
        return 0

    if action == "create":
        try:
            p = mgr.create_profile(
                display_name=args.name,
                profile_id=args.profile_id,
                description=args.desc,
                is_primary=args.primary,
            )
            print(f"✓ Created Stella profile: {p.display_name} (ID: {p.id}) at {p.path}")
            return 0
        except Exception as exc:
            print(f"Error creating profile: {exc}", file=sys.stderr)
            return 1

    if action == "rename":
        try:
            p = mgr.update_profile(profile_id=args.id, display_name=args.new_name)
            print(f"✓ Renamed profile {p.id} display name to: {p.display_name}")
            return 0
        except Exception as exc:
            print(f"Error renaming profile: {exc}", file=sys.stderr)
            return 1

    if action == "delete":
        try:
            mgr.delete_profile(profile_id=args.id, force=args.force, archive=not args.purge)
            mode = "purged" if args.purge else "archived"
            print(f"✓ Profile {args.id} {mode} successfully.")
            return 0
        except Exception as exc:
            print(f"Error deleting profile: {exc}", file=sys.stderr)
            return 1

    print(f"Unknown profile action: {action}")
    return 1


def _handle_migrate_cmd(args):
    action = getattr(args, "stella_migrate_action", None)
    engine = HermesMigrationEngine()

    if action == "detect":
        detected = engine.detect_hermes_installations()
        print(f"\nDetected Hermes Installations ({len(detected)} found):")
        for d in detected:
            print(f"  • {d.path}")
            print(f"    Config: {'yes' if d.has_config else 'no'} | Soul: {'yes' if d.has_soul else 'no'}")
            print(f"    Skills: {d.skill_count} | Memories: {d.memory_count} | Profiles: {len(d.named_profiles)}")
        print()
        return 0

    source = args.source
    if not source:
        detected = engine.detect_hermes_installations()
        if not detected:
            print("Error: No Hermes installation automatically detected. Specify path manually.", file=sys.stderr)
            return 1
        source = str(detected[0].path)
        print(f"Auto-selected detected Hermes source: {source}")

    if action == "preview":
        try:
            prev = engine.preview_migration(
                source_path=source,
                target_profile_id=args.target,
                components=args.components,
            )
            print(f"\nMigration Preview from: {prev.source_path}")
            print(f"Target Stella Profile ID: {prev.target_profile_id}")
            print("\nComponents:")
            for name, comp in prev.components.items():
                status = "✓ Available" if comp.available else "- None"
                print(f"  • {name:10}: {status} ({comp.file_count} files, {comp.total_bytes} bytes)")
                if comp.sample_files:
                    print(f"    Samples: {', '.join(comp.sample_files[:3])}")
            if prev.conflicts:
                print(f"\nConflicts with existing target ({len(prev.conflicts)} files):")
                for c in prev.conflicts[:5]:
                    print(f"  ! {c}")
            print()
            return 0
        except Exception as exc:
            print(f"Preview failed: {exc}", file=sys.stderr)
            return 1

    if action == "run":
        try:
            print(f"Starting selective migration from: {source} -> profile '{args.target}'...")
            manifest = engine.execute_migration(
                source_path=source,
                target_profile_id=args.target,
                components=args.components,
                overwrite=args.overwrite,
                import_named_profiles=args.include_profiles,
            )
            print(f"\n✓ Migration {manifest.status}!")
            print(f"  Copied files: {len(manifest.copied_files)}")
            print(f"  Skipped files: {len(manifest.skipped_files)}")
            print(f"  Audit manifest written to: {args.target}/migration_manifest.json\n")
            return 0
        except Exception as exc:
            print(f"Migration failed: {exc}", file=sys.stderr)
            return 1

    if action == "rollback":
        try:
            pdir = engine.profile_mgr.get_profile_dir(args.target)
            success = engine.rollback_migration(pdir)
            if success:
                print(f"✓ Migration cleanly rolled back for profile '{args.target}'.")
                return 0
            else:
                print(f"No active migration found to roll back in profile '{args.target}'.", file=sys.stderr)
                return 1
        except Exception as exc:
            print(f"Rollback failed: {exc}", file=sys.stderr)
            return 1

    print(f"Unknown migrate action: {action}")
    return 1
