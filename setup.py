from setuptools import setup


setup(
    name="default-spider",
    version="0.1.0",
    description="Config-driven async tender spider framework",
    packages=[
        "spider",
        "spider.config",
        "spider.core",
        "spider.extract",
        "spider.fetch",
        "spider.pipeline",
        "spider.utils",
    ],
    python_requires=">=3.6",
    install_requires=[
        "httpx>=0.22,<0.24; python_version < '3.7'",
        "httpx>=0.27.0; python_version >= '3.7'",
        "redis>=3.5,<4.0; python_version < '3.7'",
        "redis>=5.0.0; python_version >= '3.7'",
        "pydantic>=1.9,<3",
        "PyYAML>=5.4",
        "lxml>=4.9.0",
        "cssselect>=1.1.0",
        "readability-lxml>=0.8.1",
        "jsonpath-ng>=1.6.1",
        "chardet>=3.0.4",
        "apscheduler>=3.9.1",
        "typing_extensions>=4.1.1; python_version < '3.8'",
        "dataclasses>=0.8; python_version < '3.7'",
    ],
    extras_require={
        "test": [
            "pytest>=6.2,<8",
            "pytest-asyncio>=0.14,<0.17; python_version < '3.7'",
            "pytest-asyncio>=0.14,<0.21; python_version >= '3.7'",
        ]
    },
    entry_points={"console_scripts": ["spider=spider.cli:main"]},
)
