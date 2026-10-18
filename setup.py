"""Include the canonical web workspace in built distributions."""
from pathlib import Path
from shutil import copytree

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithWeb(build_py):
    def run(self):
        super().run()
        copytree(Path(__file__).parent / "web", Path(self.build_lib) / "likethis" / "web", dirs_exist_ok=True)


setup(cmdclass={"build_py": BuildWithWeb})
