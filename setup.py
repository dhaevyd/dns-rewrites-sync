"""Package setup"""

from setuptools import setup, find_packages

setup(
    name="dns-rewrites-sync",
    version="1.0.0",
    description="Universal DNS Rewrites Synchronization Tool",
    author="Your Name",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "pyyaml>=6.0",
        "cryptography>=41.0.0",
        "tabulate>=0.9.0",
    ],
    entry_points={
        "console_scripts": [
            "dns-sync = dns_sync.cli:main",
        ],
    },
    python_requires=">=3.8",
)