import socket
import os
import datetime
import sys
import select
import signal

HOST = '0.0.0.0'
PORT = 9090
running = True
current_conn = None
BUFFER_SIZE = 1024
CHUNK_SIZE = 4096

def signal_handler(sig, frame):
    global running
    running = False
    if current_conn:
        current_conn.close()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def setup_keepalive(sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if sys.platform == 'win32':
        sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30000, 10000))
    elif hasattr(socket, 'TCP_KEEPIDLE'):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)

def read_line(conn):
    line = b''
    while running:
        try:
            read_list, _, _ = select.select([conn], [], [], 0.5)
            if not read_list:
                continue
            data = conn.recv(CHUNK_SIZE)
            if not data:
                return None
            line = data.split(b'\r\n')[0]
            return line.decode('utf-8', errors='ignore').strip()
        except:
            return None
    return None

def handle_echo(conn, args):
    msg = " ".join(args) + "\n"
    conn.sendall(msg.encode())

def handle_time(conn):
    time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
    conn.sendall(time_str.encode())

def handle_download(conn, args):
    if len(args) < 2:
        conn.sendall(b"ERROR invalid arguments\n")
        return
    filename, offset_str = args[0], args[1]

    try:
        offset = int(offset_str)
        if not os.path.exists(filename) or not os.path.isfile(filename):
            conn.sendall(b"ERROR file not found\n")
            return

        filesize = os.path.getsize(filename)
        conn.sendall(f"OK {filesize}\n".encode())

        if offset >= filesize:
            return

        with open(filename, 'rb') as f:
            f.seek(offset)
            while running:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                conn.sendall(chunk)
    except Exception as e:
        pass

def handle_upload(conn, args):
    if len(args) < 2:
        conn.sendall(b"ERROR invalid arguments\n")
        return
    filename, filesize_str = args[0], args[1]

    try:
        filesize = int(filesize_str)
        offset = os.path.getsize(filename) if os.path.exists(filename) else 0

        conn.sendall(f"OK {offset}\n".encode())

        if offset >= filesize:
            return

        remaining = filesize - offset
        with open(filename, 'ab') as f:
            while remaining > 0 and running:
                read_list, _, _ = select.select([conn], [], [], 0.5)
                if not read_list:
                    continue
                chunk = conn.recv(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
    except Exception as e:
        pass

def process_client(conn, addr):
    global current_conn
    current_conn = conn
    print(f"Client connected: {addr}")
    conn.settimeout(None)
    try:
        while running:
            data = read_line(conn)
            if data is None:
                break

            parts = data.split()
            if not parts:
                continue

            cmd = parts[0].upper()
            if cmd == 'ECHO':
                handle_echo(conn, parts[1:])
            elif cmd == 'TIME':
                handle_time(conn)
            elif cmd in ('CLOSE', 'EXIT', 'QUIT'):
                break
            elif cmd == 'DOWNLOAD':
                handle_download(conn, parts[1:])
            elif cmd == 'UPLOAD':
                handle_upload(conn, parts[1:])
            else:
                conn.sendall(b"UNKNOWN COMMAND\n")
    except ConnectionResetError:
        pass
    except Exception:
        pass
    finally:
        print(f"Client disconnected: {addr}")
        conn.close()
        current_conn = None


def main():
    global running, PORT
    signal.signal(signal.SIGINT, signal_handler)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    setup_keepalive(s)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        PORT = int(input("Enter port for server (default 9090): ").strip())
    except ValueError:
        print("Invalid input! Using default port.")
        s.bind((HOST, PORT))

    s.listen(1)
    s.settimeout(0.5)

    local_ip = get_local_ip()
    print(f"Server is listening on 0.0.0.0:{PORT}")
    print(f"Your Local IP for client to connect: {local_ip}")

    try:
        while running:
            try:
                conn, addr = s.accept()
                process_client(conn, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if running:
                    print(f"Server error: {e}")
    finally:
        if current_conn:
            current_conn.close()
        s.close()
        print("Server stopped")


if __name__ == '__main__':
    main()