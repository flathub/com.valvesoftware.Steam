from setuptools import setup

setup(
    name="steam_wrapper",
    description="Steam wrapper for Steam Flatpak",
    py_modules=["steam_wrapper"],
    version="1.0.0",
    entry_points={
        "console_scripts": [
            "steam-wrapper = steam_wrapper:main"
        ]
    }
)
