from tui.app import RagApp


def main():
    """Mneme TUI 入口点，注册为 console_scripts `mneme` 命令。"""
    RagApp().run()


if __name__ == "__main__":
    main()
