#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = ['Click>=8.0.3', 'beautifulsoup4>=4.10.0', 'python-dateutil>=2.8.2', 'requests>=2.27.1', 'pydantic>=1.9.0','parsel>=1.6.0']

setup_requirements = ['pytest-runner', ]

test_requirements = ['pytest>=3', ]

setup(
    author="Innerkore",
    author_email='admin@innerkore.com',
    python_requires='>=3.7',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    description="Shipkore tracking library and CLI",
    entry_points={
        'console_scripts': [
            'libshipkore=libshipkore.cli:main',
        ],
    },
    install_requires=requirements,
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='libshipkore',
    name='libshipkore',
    packages=find_packages(include=['libshipkore', 'libshipkore.*']),
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/shipkore/libshipkore',
    version='0.4.1',
    zip_safe=False,
)
