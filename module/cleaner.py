import os
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent



def delete_file(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except PermissionError:
        try:
            os.chmod(path, 0o666)
            path.unlink()
            return True
        except Exception as e:
            print(f"Cannot be removed: {path} -> {e}")
            return False
    except Exception as e:
        print(f"Cannot be removed: {path} -> {e}")
        return False


def clear_assets_files(folder_name: str = "../assets") -> None:
    assets_dir = get_base_dir() / folder_name

    if not assets_dir.is_dir():
        print(f"folder '{assets_dir}' not founded.")
        return

    deleted, failed = 0, 0

    for root, dirs, files in os.walk(assets_dir, followlinks=False):
        root_path = Path(root)

        for d in dirs:
            p = root_path / d
            if p.is_symlink():
                if delete_file(p):
                    deleted += 1
                else:
                    failed += 1

        for f in files:
            if delete_file(root_path / f):
                deleted += 1
            else:
                failed += 1

    print(f"deleted: {deleted} | failed: {failed}")
