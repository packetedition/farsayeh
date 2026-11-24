'''
Manage Logs and Log levels
1 for info
2 for warning
3 for fatal
'''
from colorama import init, Fore
def logger(level: int, message: str, message_head = "log") -> None:
    init(autoreset=True)
    match level:
        case 1:
            print(Fore.BLUE + "[" + message_head + "]: " + message)
        case 2:
            print(Fore.YELLOW + "[" + message_head + "]: " + message)
        case 3:
            print(Fore.RED + "[" + message_head + "]: " + message)
        case _:
            print(Fore.YELLOW + "[Log]: Log level is not valid!")
