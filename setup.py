"""Setup main garmin_guard package."""

from setuptools import find_packages
from setuptools import setup


with open("requirements.txt", encoding="utf-8") as f:
    content = f.readlines()
requirements = [x.strip() for x in content if "git+" not in x]


setup(name='package_folder',
      version="0.0.1",
      install_requires=requirements,
      description="Garmin Guard Training")
