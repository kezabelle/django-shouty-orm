#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
from setuptools import setup
if sys.version_info[0] == 2:
    # get the Py3K compatible `encoding=` for opening files.
	from io import open


HERE = os.path.abspath(os.path.dirname(__file__))


def make_readme(root_path):
    consider_files = ("README.rst", "LICENSE", "CHANGELOG", "CONTRIBUTORS")
    for filename in consider_files:
        filepath = os.path.realpath(os.path.join(root_path, filename))
        if os.path.isfile(filepath):
            with open(filepath, mode="r", encoding="utf-8") as f:
                yield f.read()

LICENSE = "BSD License"
URL = "https://github.com/kezabelle/django-shouty-orm"
LONG_DESCRIPTION = "\r\n\r\n----\r\n\r\n".join(make_readme(HERE))
SHORT_DESCRIPTION = "Applies a monkeypatch which forces Django's ORM to error far more loudly in certain cases"
KEYWORDS = (
    "django",
    "orm",
    "sql",
    "exception",
)

setup(
    name="django-shouty-orm",
    version="0.1.1",
    author="Keryn Knight",
    author_email="django-shouty-orm@kerynknight.com",
    maintainer="Keryn Knight",
    maintainer_email="django-shouty-orm@kerynknight.com",
    description=SHORT_DESCRIPTION[0:200],
    long_description=LONG_DESCRIPTION,
    packages=[],
    py_modules=["shoutyorm"],
    include_package_data=True,
    install_requires=["Django>=2.2", "wrapt>=1.11",],
    zip_safe=False,
    keywords=" ".join(KEYWORDS),
    license=LICENSE,
    url=URL,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: {}".format(LICENSE),
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Framework :: Django",
    ],
)
