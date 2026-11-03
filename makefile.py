import getopt
import hashlib
import os
import py_compile
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from tools.check_language import check_library
from tools.check_native_build import check_plain_path, copy_runtime
from tools.check_package_files import check_package_files
from tools.version_info import validate_version

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "clnch"))
import clnch_resource

sys.path[0:0] = [
    os.path.join( os.path.split(sys.argv[0])[0], '..' ),
    ]

#-------------------------------------------

action = "all"

debug = False

option_list, args = getopt.getopt( sys.argv[1:], "d", [] )
for option in option_list:
    if option[0]=="-d":
        debug = True

if len(args)>0:
    action = args[0]

#-------------------------------------------

PYTHON_DIR = "Python315/tools"

PYTHON = PYTHON_DIR + "/python.exe"

CONFIGURATION = "Debug" if debug else "Release"
RUN_DIR = f"build/run/x64/{CONFIGURATION}"

DOXYGEN_DIR = "third_party/doxygen"

DIST_DIR = "dist/ReCraftLaunch"
VERSION = clnch_resource.clnch_version
validate_version(VERSION)
ARCHIVE_NAME = f"ReCraftLaunch_{VERSION}.zip"

NATIVE_PROJECTS = (
    "ReCraftLaunch.vcxproj",
    "clnch_native/clnch_native.vcxproj",
    "ckit/ckitcore/ckitcore.vcxproj",
    "pyauto/pyautocore/pyautocore.vcxproj",
)

# Complete copy list: repository source -> package destination.
COPY_ITEMS = {
    "build/run/x64/Release/reclnch.exe": "reclnch.exe",
    "build/run/x64/Release/python315.dll": "python315.dll",
    "build/run/x64/Release/library.zip": "library.zip",
    "samples/_custom.py": "settings/_custom.py",
    "samples/_commands.json": "settings/_commands.json",
    "samples/scripts": "settings/scripts",
    "extensions/stamp.py": "extensions/stamp.py",
    "extensions/netdrive.py": "extensions/netdrive.py",
    "extensions/clock.py": "extensions/clock.py",
    "extensions/completion_keys.py": "extensions/completion_keys.py",
    "extensions/list_keys.py": "extensions/list_keys.py",
    "LICENSE.md": "LICENSE.md",
    "docs/ja/readme.txt": "README.ja.txt",
    "docs/en/readme.txt": "README.en.txt",
    "docs/ja/commands.md": "COMMANDS.ja.md",
    "docs/en/commands.md": "COMMANDS.en.md",
    "docs/html/ja": "docs/ja",
    "docs/html/en": "docs/en",
    "build/run/x64/Release/lib": "lib",
    "themes/black.ini": "themes/black.ini",
    "themes/white.ini": "themes/white.ini",
    "themes/gray.ini": "themes/gray.ini",
    "licenses": "licenses",
    "ckit/LICENSE.md": "licenses/ckit_LICENSE.md",
    "pyauto/LICENSE.md": "licenses/pyauto_LICENSE.md",
}

#-------------------------------------------

def unlink(filename):
    try:
        os.unlink(filename)
    except OSError:
        pass

def makedirs(dirname):
    try:
        os.makedirs(dirname)
    except OSError:
        pass

def rmtree(dirname):
    try:
        shutil.rmtree(dirname)
    except OSError:
        pass

def compilePythonRecursively( src, dst, file_black_list=(), directory_black_list=() ):

    for root, dirs, files in os.walk( src ):

        for directory_to_remove in directory_black_list:
            if directory_to_remove in dirs:
                dirs.remove(directory_to_remove)

        for file_to_remove in file_black_list:
            if file_to_remove in files:
                files.remove(file_to_remove)

        for filename in files:
            if filename.endswith(".py"):
                src_filename = os.path.join(root,filename)
                dst_filename = os.path.join(dst+root[len(src):],filename+"c")
                print("compile", src_filename, dst_filename )
                py_compile.compile( src_filename, dst_filename, optimize=2, doraise=True )


def createZip( zip_filename, items ):
    z = zipfile.ZipFile( zip_filename, "w", zipfile.ZIP_DEFLATED, True, compresslevel=9 )
    for item in items:
        if os.path.isdir(item):
            for root, dirs, files in os.walk(item):
                dirs.sort()
                for f in sorted(files):
                    f = os.path.normpath(os.path.join(root,f))
                    print( f )
                    z.write(f)
        else:
            print( item )
            z.write(item)
    z.close()


#-------------------------------------------

def target_all():

    target_dist()
    target_archive(verified=True)


def target_release():

    target_all()


def target_compile():

    makedirs("build/run/x64/Release")
    library_zip = os.path.abspath("build/run/x64/Release/library.zip")
    if os.path.exists(library_zip):
        os.remove(library_zip)
    if os.path.exists("build/Lib"):
        shutil.rmtree("build/Lib")

    # compile python source files
    compilePythonRecursively( f"{PYTHON_DIR}/Lib", "build/Lib", 
        # Tcl/Tk is not copied; turtle requires tkinter.
        file_black_list = ["turtle.py"],
        directory_black_list = [
            "site-packages",
            "test",
            "tests",
            "idlelib",
            "tkinter",
            "turtledemo",
            # No Python CLI, venv launchers/scripts or bundled pip wheel are shipped.
            "venv",
            "ensurepip",
            ]
        )
    compilePythonRecursively( "clnch", "build/Lib" )
    compilePythonRecursively( "ckit", "build/Lib/ckit",
        file_black_list=["makefile.py"], directory_black_list=["test"]
        )
    compilePythonRecursively( "pyauto", "build/Lib/pyauto",
        file_black_list=["makefile.py"], directory_black_list=["sample", "doc", "tool"]
        )

    # archive python compiled files
    os.chdir("build/Lib")
    createZip( library_zip, "." )
    os.chdir("../..")
    check_library(library_zip)


def target_copy(run_dir=RUN_DIR):

    copy_runtime(run_dir, Path(PYTHON_DIR))

    os.makedirs(f"{run_dir}/settings/scripts", exist_ok=True)
    for sample, name in (("_custom.py", "custom.py"), ("_commands.json", "commands.json")):
        destination = f"{run_dir}/settings/{name}"
        if not os.path.exists(destination):
            shutil.copy(f"samples/{sample}", destination)

    # Development resources stay in the repository; settings use RUN_DIR/settings.
    with open(f"{run_dir}/sitecustomize.py", "w", encoding="utf-8") as f:
        f.write('import os, sys\n'
                'sys._clnch_app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))\n'
                'sys.path.append(sys._clnch_app_dir)\n')


def target_document():
    subprocess.run([os.path.abspath(PYTHON), "-B", "-c", "import docutils, pygments"], check=True)
    for language in ("ja", "en"):
        document_language(language)
    groups = {
        lang: {name for name in os.listdir(f"docs/html/{lang}")
               if name.startswith("group__") and name.endswith(".js")}
        for lang in ("ja", "en")
    }
    if groups["ja"] != groups["en"]:
        raise ValueError("Japanese/English API groups differ")
    for name in sorted(groups["ja"]):
        with open(f"docs/html/ja/{name}", "rb") as japanese, open(f"docs/html/en/{name}", "rb") as english:
            if japanese.read() != english.read():
                raise ValueError(f"Japanese/English API members differ: {name}")
    print(f"Checked matching Japanese/English members in {len(groups['ja'])} API groups.")


def document_language(lang):
    python = os.path.abspath(PYTHON)

    doxygen = os.path.abspath(DOXYGEN_DIR + "/bin/doxygen.exe")
    if not os.path.isfile(doxygen):
        raise FileNotFoundError(doxygen)

    source_dir = f"docs/{lang}"
    if lang not in ("ja", "en") or not os.path.isdir(source_dir):
        raise ValueError(f"Documentation is not available for language: {lang}")
    output = f"docs/html/{lang}"
    objects = f"docs/obj/{lang}"
    rmtree(output)
    rmtree(objects)
    makedirs(objects)
    makedirs(output)

    for name in ("index", "changes", "differences", "command_json"):
        if name == "changes":
            source = "docs/common/changes.txt"
        else:
            source = f"{source_dir}/{name}.txt"
        if name == "index":
            with open(source, encoding="utf-8-sig") as original:
                text = original.read()
            source = f"{objects}/index.txt"
            with open(source, "w", encoding="utf-8") as staged:
                staged.write(text.replace("{{APP_VERSION}}", VERSION))
        subprocess.run([python, "-B", "tools/rst2html_pygments.py", "--stylesheet=",
                        "--template=tools/rst2html_template.txt", f"--language={lang}",
                        source, f"{objects}/{name}.htm_"], check=True)

    # Doxygen renders Markdown pages, including tables and fenced code blocks.
    with open(f"{source_dir}/commands.md", encoding="utf-8-sig") as source:
        title, body = source.read().split("\n", 1)
    with open(f"{objects}/commands.md", "w", encoding="utf-8") as page:
        page.write(f"{title} {{#commands}}\n{body}")
    with open(f"{source_dir}/extensions.md", encoding="utf-8-sig") as source:
        title, body = source.read().split("\n", 1)
    with open(f"{objects}/extensions.md", "w", encoding="utf-8") as page:
        page.write(f"{title} {{#extensions}}\n{body}")
    shutil.copyfile(f"{source_dir}/licenses.md", f"{objects}/licenses.md")
    for source, name in (("LICENSE.md", "recraftlaunch"),
                         ("licenses/craftlaunch_LICENSE.md", "craftlaunch"),
                         ("ckit/LICENSE.md", "ckit"), ("pyauto/LICENSE.md", "pyauto")):
        shutil.copyfile(source, f"{objects}/license_{name}.md")
    # Preserve plain-text layout and punctuation instead of interpreting it as Markdown.
    for name in ("python", "expat"):
        with open(f"licenses/{name}_LICENSE.txt", encoding="utf-8-sig") as source:
            text = source.read()
        with open(f"{objects}/license_{name}.md", "w", encoding="utf-8") as staged:
            staged.write("\\verbatim\n" + text + "\n\\endverbatim\n")

    language = "Japanese" if lang == "ja" else "English"
    with open(f"{objects}/doxyfile", "w", encoding="utf-8") as config:
        config.write(f"@INCLUDE = docs/doxyfile\nOUTPUT_LANGUAGE = {language}\n"
                     f"PROJECT_NUMBER = {VERSION}\n"
                     f"ENABLED_SECTIONS = {language.lower()}\nHTML_OUTPUT = html/{lang}\n"
                     f"EXAMPLE_PATH = {objects}\nMARKDOWN_ID_STYLE = GITHUB\n"
                     f"INPUT += {objects}/commands.md {objects}/extensions.md {objects}/licenses.md\n")
    subprocess.run([doxygen, f"{objects}/doxyfile"], check=True)
    shutil.copytree(f"docs/{lang}/images", f"{output}/images", ignore=shutil.ignore_patterns("*.pdn",))
    with open(f"{output}/language.txt", "w", encoding="utf-8") as marker:
        marker.write(lang + "\n")
    subprocess.run([python, "-B", "tools/check_docs.py", "--lang", lang], check=True)


def find_msbuild():
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        raise FileNotFoundError(vswhere)
    result = subprocess.run(
        [str(vswhere), "-latest", "-products", "*", "-version", "[18.0,19.0)",
         "-requires", "Microsoft.Component.MSBuild", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
         "-property", "installationPath"], capture_output=True, text=True, check=True,
    )
    installation = result.stdout.strip()
    if not installation:
        raise RuntimeError("Visual Studio 2026 with MSBuild and C++ tools (v145) is required.")
    msbuild = Path(installation) / "MSBuild/Current/Bin/MSBuild.exe"
    if not msbuild.is_file():
        raise FileNotFoundError(msbuild)
    return msbuild


def check_package_outputs():
    # Check before Rebuild, bytecode generation, or package removal; never follow links.
    root = Path.cwd()
    for name in (DIST_DIR, "build/Lib", "build/run/x64/Release/lib", "build/obj",
                 "build/run/x64/Release/reclnch.exe", "build/run/x64/Release/python315.dll"):
        path = Path(os.path.abspath(name))
        if path == root or not path.is_relative_to(root):
            raise ValueError("The output directory must be inside this repository.")
        check_plain_path(path)
        if path.is_dir():
            for directory, dirs, files in os.walk(path):
                for entry in dirs + files:
                    check_plain_path(Path(directory) / entry)


def target_dist():
    python = os.path.abspath(PYTHON)
    if not Path(python).is_file():
        raise FileNotFoundError(python)
    msbuild = find_msbuild()
    for name in ("clnch/clnch_standard.py", "samples/_custom.py", "samples/_commands.json",
                 "clnch/clnch_cmdeditor.py", "clnch/clnch_cmdlist.py", "clnch/clnch_cmdstore.py",
                 "clnch/clnch_execonfig.py", "clnch/clnch_modifierconfig.py", "clnch/clnch_altenterconfig.py",
                 *NATIVE_PROJECTS):
        if not Path(name).is_file():
            raise FileNotFoundError(name)
    check_package_outputs()

    for project in NATIVE_PROJECTS:
        print(f"Build: {project} (Release|x64)", flush=True)
        subprocess.run([str(msbuild), project, "/t:Rebuild", "/p:Configuration=Release",
                        "/p:Platform=x64", "/nologo", "/verbosity:quiet"], check=True)

    target_compile()
    # Distribution always uses Release, including when -d was supplied for development copy.
    target_copy("build/run/x64/Release")
    target_document()

    for source in COPY_ITEMS:
        if not Path(source).exists():
            raise FileNotFoundError(source)
    package = Path(DIST_DIR)
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)
    for source, destination in COPY_ITEMS.items():
        target = package / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(source).is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

    check_package_files(package, generated_docs="docs/html")
    for language in ("ja", "en"):
        subprocess.run([python, "-I", "-S", "-B", "tools/check_package.py", str(package), language], check=True)
    print(f"Completed: {DIST_DIR}/ (Japanese + English)")


def target_archive(verified=False):

    # all/release just validated this unchanged folder; standalone archive checks it independently.
    if not verified:
        check_package_files(DIST_DIR)
    makedirs("dist")

    os.chdir("dist")
    createZip( ARCHIVE_NAME, [os.path.basename(DIST_DIR)] )
    os.chdir("..")
    with zipfile.ZipFile(f"dist/{ARCHIVE_NAME}") as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt distribution archive")

    with open( f"dist/{ARCHIVE_NAME}", "rb" ) as fd:
        m = hashlib.sha256()
        while 1:
            data = fd.read( 1024 * 1024 )
            if not data:
                break
            m.update(data)
    print()
    print(f"SHA256 {ARCHIVE_NAME}: {m.hexdigest()}")


def target_clean():
    rmtree("dist")
    rmtree("build")
    rmtree("docs/html")
    rmtree("docs/obj")
    unlink( "tags" )


#-------------------------------------------

if __name__ == "__main__":
    eval( "target_" + action +"()" )
