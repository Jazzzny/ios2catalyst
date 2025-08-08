import sys
import subprocess
from io import BytesIO
from pathlib import Path

import macholib.MachO
from macholib.mach_o import LC_BUILD_VERSION, PLATFORM_NAMES, LC_VERSION_MIN_IPHONEOS, LC_VERSION_MIN_MACOSX, LC_VERSION_MIN_TVOS, LC_VERSION_MIN_WATCHOS

def platform_name_from_int(platform_code):
    return PLATFORM_NAMES.get(platform_code)

def encode_os_version(major, minor, patch):
    return (major << 16) | (minor << 8) | patch

def decode_os_version(minos):
    return (minos >> 16) & 0xFF, (minos >> 8) & 0xFF, minos & 0xFF

def adhoc_codesign(binary_path):
    try:
        subprocess.run(["codesign", "--force", "--sign", "-", binary_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during ad-hoc codesign: {e}")
        sys.exit(1)

def ios_build_to_macos(minos):
    # Map iOS minos to Mac Catalyst minos
    major, _, _ = decode_os_version(minos)
    # Predates Mac catalyst, so just set to 11.0
    if major < 14:
        return encode_os_version(11, 0, 0)
    else:
        # i.e. iOS 18 = macOS 15, don't care about minor and patch
        return encode_os_version(major - 3, 0, 0)

def patch_macho(binary_path):
    print(f"\nPatching Mach-O: {binary_path}")
    original_file = BytesIO(binary_path.read_bytes())
    machFile = macholib.MachO.MachO(binary_path)

    for cmd in machFile.headers[0].commands:
        if cmd[0].cmd == LC_BUILD_VERSION or cmd[0].cmd in (LC_VERSION_MIN_IPHONEOS, LC_VERSION_MIN_TVOS, LC_VERSION_MIN_WATCHOS):
            if cmd[0].cmd in (LC_VERSION_MIN_IPHONEOS, LC_VERSION_MIN_TVOS, LC_VERSION_MIN_WATCHOS):
                print(f"  Command: {"LC_VERSION_MIN_IPHONEOS" if cmd[0].cmd == LC_VERSION_MIN_IPHONEOS else "LC_VERSION_MIN_TVOS" if cmd[0].cmd == LC_VERSION_MIN_TVOS else "LC_VERSION_MIN_WATCHOS"}")
                cmd[0].cmd = LC_VERSION_MIN_MACOSX
                print("  Changed command to LC_VERSION_MIN_MACOSX, note that this will not work if this binary links iOS-only frameworks!!!")

                # Set version to macOS equivalent
                old_version = cmd[1].version
                print(f"  version = {old_version} {decode_os_version(old_version)}")
                new_version = ios_build_to_macos(old_version)
                cmd[1].version = new_version
                print(f"  Set version to {new_version} {decode_os_version(new_version)}")
            else:
                # Set platform to Mac Catalyst
                old_platform = cmd[1].platform
                print(f"  platform = {old_platform} ({platform_name_from_int(old_platform)})")
                cmd[1].platform = 6  # Mac Catalyst
                print(f"  Set platform to 6 ({platform_name_from_int(6)})")

                # Set minos to macOS equivalent
                old_minos = cmd[1].minos
                print(f"  minos = {old_minos} {decode_os_version(old_minos)}")
                new_minos = ios_build_to_macos(old_minos)
                cmd[1].minos = new_minos
                print(f"  Set minos to {new_minos} {decode_os_version(new_minos)}")

            # Set sdk to macOS equivalent
            old_sdk = cmd[1].sdk
            print(f"  sdk = {old_sdk} {decode_os_version(old_sdk)}")
            new_sdk = ios_build_to_macos(old_sdk)
            cmd[1].sdk = new_sdk
            print(f"  Set sdk to {new_sdk} {decode_os_version(new_sdk)}")

    with open(binary_path, "wb") as new_file:
        machFile.headers[0].write(new_file)
        original_file.seek(new_file.tell())
        new_file.write(original_file.read())

    adhoc_codesign(binary_path)
    print("  Codesigned successfully")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <.app path>")
        sys.exit(1)

    app_path = Path(sys.argv[1])
    if not app_path.exists():
        print("Error: must provide a valid .app directory or binary path")
        sys.exit(1)

    if app_path.is_dir():
        # Patch all Mach-O binaries inside .app
        for file_path in app_path.rglob("*"):
            if file_path.is_file():
                try:
                    macholib.MachO.MachO(file_path)
                    patch_macho(file_path)
                except Exception as e:
                    if "Unknown Mach-O header" not in str(e):
                        print(f"Error: {e}")

        print(f"\nCodesigning the entire app bundle: {app_path}")
        adhoc_codesign(app_path)

    else:
        # Single binary file
        try:
            macholib.MachO.MachO(app_path)
            patch_macho(app_path)
        except Exception as e:
            if "Unknown Mach-O header" not in str(e):
                print(f"Error: {e}")
            else:
                print(f"Error: provided file is not a valid Mach-O binary: {app_path}")
                sys.exit(1)


    print("\nAll patches complete.")