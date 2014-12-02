#!/usr/bin/env python

from setuptools import setup

__version__ = '0.0.1'

CLASSIFIERS = map(str.strip,
"""Environment :: Console
License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)
Natural Language :: English
Operating System :: POSIX :: Linux
Programming Language :: Python
Programming Language :: Python :: 2.7
""".splitlines())

entry_points = {
    'console_scripts': [
        'bts_to_github_sync = bts_to_github.main:main',
    ]
}

setup(
    name="debian_bts_to_github_sync",
    version=__version__,
    author="Federico Ceratto",
    author_email="federico.ceratto@gmail.com",
    description="Debian BTS to GitHub Issue sync",
    license="AGPLv3+",
    url="https://github.com/FedericoCeratto/desktop-security-assistant",
    long_description="",
    classifiers=CLASSIFIERS,
    keywords="",
    install_requires=[
        'setproctitle>=1.0.1',
    ],
    packages=['bts_to_github'],
    package_dir={'bts_to_github_sync': 'bts_to_github_sync'},
    platforms=['Linux'],
    zip_safe=False,
    entry_points=entry_points,
)
