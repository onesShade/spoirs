import socket
import os
import sys
import time
import select

HOST = '127.0.0.1'
PORT = 9090
CHUNK_SIZE = 4096
RETRY_AMOUNT = 5

def setup_keepalive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if sys.platform == 'win32':
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
    elif hasattr(socket, 'TCP_KEEPIDLE'):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)


def get_input_and_check_socket_win(sock):
    input_buf = []

    import msvcrt
    while True:
        read_list, _, error_list = select.select([sock], [], [sock], 0.0)
        if sock in [read_list, error_list]:
            try:
                data = sock.recv(1, socket.MSG_PEEK)
                if not data:
                    print("\n[!] Server closed connection.")
                    return None
            except Exception:
                print("\n[!] Connection lost (KeepAlive timeout).")
                return None

        if msvcrt.kbhit():
            c = msvcrt.getwch()
            if c == '\r':
                print()
                return ''.join(input_buf).strip()
            elif c == '\x08':
                if input_buf:
                    input_buf.pop()
                    sys.stdout.write('\b \b')
                    sys.stdout.flush()
            elif c == '\x03':
                raise KeyboardInterrupt
            else:
                input_buf.append(c)
                sys.stdout.write(c)
                sys.stdout.flush()
        else:
            time.sleep(0.01)


def get_input_and_check_socket_linux(sock):
    input_buf = []
    while True:
        read_list, _, error_list = select.select([sys.stdin, sock], [], [sock], 0.1)
        if sock in [read_list, error_list]:
            try:
                data = sock.recv(1, socket.MSG_PEEK)
                if not data:
                    print("\n[!] Server closed connection.")
                    return None
            except Exception:
                print("\n[!] Connection lost (KeepAlive timeout).")
                return None
        if sys.stdin in read_list:
            return sys.stdin.readline().strip()


def get_input_and_check_socket(sock):
    sys.stdout.write("> ")
    sys.stdout.flush()

    if sys.platform == 'win32':
        return get_input_and_check_socket_win(sock)
    else:
        return get_input_and_check_socket_linux(sock)


def read_line(conn):
    line = b''
    while True:
        read_list, _, _ = select.select([conn], [], [], 0.5)
        if not read_list:
            continue
        data = conn.recv(CHUNK_SIZE)
        if not data:
            return None
        line = data.split(b'\r\n')[0]
        return line.decode('utf-8', errors='ignore').strip()


def connect_to_server_manual():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            setup_keepalive(s)
            s.connect((HOST, PORT))
            print(f"Connected to {HOST}:{PORT} successfully.")
            return s
        except Exception:
            print(f"Server at {HOST}:{PORT} is not running or unreachable.")
            ans = input("Do you want to retry? (y/n): ").strip().lower()
            if ans != 'y':
                sys.exit(0)


def attempt_auto_reconnect():
    sys.stdout.write("\nConnection lost! Auto-reconnecting...\n")
    for _ in range(RETRY_AMOUNT):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            setup_keepalive(s)
            s.connect((HOST, PORT))
            return s
        except Exception:
            time.sleep(2)
    return None


def calc_bitrate(bytes_transferred, duration):
    if duration <= 0:
        duration = 0.001
    mbps = ((bytes_transferred * 8) / duration) / 1024 / 1024
    print(f"\nTransfer finished. Bitrate: {mbps:.2f} Mbps")


def print_progress(current, total, last_printed_percent):
    if total > 0:
        percent = (current / total) * 100
        if percent - last_printed_percent >= 0.1 or current == total:
            mb_curr = current / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            sys.stdout.write(f"\rProgress: {percent:.1f}%  ({mb_curr:.0f}/{mb_total:.0f} MB)   ")
            sys.stdout.flush()
            return percent
    return last_printed_percent


def do_download(s, parts):
    if len(parts) < 2:
        print("Usage: DOWNLOAD <filename>")
        return s

    filename = parts[1]
    while True:
        offset = os.path.getsize(filename) if os.path.exists(filename) else 0
        try:
            s.sendall(f"DOWNLOAD {filename} {offset}\n".encode())
            resp_str = read_line(s)

            if not resp_str:
                raise ConnectionResetError()

            resp = resp_str.split()
            if not resp or resp[0] == "ERROR":
                err_msg = ' '.join(resp[1:]) if len(resp) > 1 else 'File not found'
                print(f"Server error: {err_msg}")
                return s

            filesize = int(resp[1])
            if offset >= filesize:
                print("\nFile already fully downloaded.")
                return s

            if offset > 0:
                print(f"Resuming download from byte {offset}...")

            start_time = time.time()
            remaining = filesize - offset
            transferred = 0
            last_percent = -1.0

            with open(filename, 'ab') as f:
                while remaining > 0:
                    r, _, _ = select.select([s], [], [], 0.5)
                    if not r:
                        continue
                    chunk = s.recv(min(4096, remaining))
                    if not chunk:
                        raise ConnectionResetError()
                    f.write(chunk)
                    remaining -= len(chunk)
                    transferred += len(chunk)
                    last_percent = print_progress(offset + transferred, filesize, last_percent)
            calc_bitrate(transferred, time.time() - start_time)
            return s

        except Exception:
            s = attempt_auto_reconnect()
            if s is None:
                print("Failed to auto-reconnect.")
                return None


def do_upload(s, parts):
    if len(parts) < 2:
        print("Usage: UPLOAD <filename>")
        return s

    filename = parts[1]
    if not os.path.exists(filename):
        print("Local file not found.")
        return s

    filesize = os.path.getsize(filename)
    while True:
        try:
            s.sendall(f"UPLOAD {filename} {filesize}\n".encode())
            resp_str = read_line(s)
            if not resp_str:
                raise ConnectionResetError()

            resp = resp_str.split()
            if not resp or resp[0] == "ERROR":
                print("Server refused upload.")
                return s

            offset = int(resp[1])
            if offset >= filesize:
                print("File already fully uploaded.")
                return s

            start_time = time.time()
            transferred = 0
            last_percent = -1.0

            with open(filename, 'rb') as f:
                f.seek(offset)
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    s.sendall(chunk)
                    transferred += len(chunk)
                    last_percent = print_progress(offset + transferred, filesize, last_percent)
            calc_bitrate(transferred, time.time() - start_time)
            return s
        except Exception:
            s = attempt_auto_reconnect()
            if s is None:
                print("Failed to auto-reconnect.")
                return None


def set_host_port():
    global HOST, PORT
    user_host = input(f"Enter server IP (default {HOST}): ").strip()
    if user_host:
        HOST = user_host
    try:
        PORT = int(input(f"Enter server port (default {PORT}): ").strip())
    except ValueError:
        print("Invalid port, using default.")


def main():
    global HOST, PORT
    set_host_port()
    s = connect_to_server_manual()

    while True:
        try:
            cmd_input = get_input_and_check_socket(s)
            if cmd_input is None:
                raise ConnectionResetError()
            if not cmd_input:
                continue

            parts = cmd_input.split()
            cmd = parts[0].upper()

            if cmd in ('CLOSE', 'EXIT', 'QUIT'):
                s.sendall(cmd_input.encode() + b'\n')
                break
            elif cmd == 'DOWNLOAD':
                s = do_download(s, parts)
                if s is None:
                    s = connect_to_server_manual()
            elif cmd == 'UPLOAD':
                s = do_upload(s, parts)
                if s is None:
                    s = connect_to_server_manual()
            else:
                s.sendall(cmd_input.encode() + b'\n')
                response = read_line(s)
                if response is None:
                    raise ConnectionResetError()
                print(response)

        except KeyboardInterrupt:
            break
        except Exception:
            s.close()
            s = connect_to_server_manual()
    s.close()

if __name__ == '__main__':
    main()