import psutil

print(f"psutil version: {psutil.__version__}")

# Получаем текущий процесс
p = psutil.Process()
print(f"Process: {p}")

# Пробуем получить соединения
try:
    connections = p.connections()
    print(f"Total connections: {len(connections)}")
    
    if connections:
        # Посмотрим структуру первого соединения
        conn = connections[0]
        print(f"Connection attributes: {dir(conn)}")
        print(f"fd: {getattr(conn, 'fd', 'N/A')}")
        print(f"family: {getattr(conn, 'family', 'N/A')}")
        print(f"type: {getattr(conn, 'type', 'N/A')}")
        print(f"laddr: {getattr(conn, 'laddr', 'N/A')}")
        print(f"raddr: {getattr(conn, 'raddr', 'N/A')}")
        print(f"status: {getattr(conn, 'status', 'N/A')}")
        
        # Посчитаем TCP соединения
        tcp_count = 0
        established = 0
        time_wait = 0
        
        for c in connections:
            if hasattr(c, 'family') and c.family in (2, 10):  # IPv4 or IPv6
                tcp_count += 1
                if hasattr(c, 'status'):
                    if c.status == 'ESTABLISHED':
                        established += 1
                    elif c.status == 'TIME_WAIT':
                        time_wait += 1
        
        print(f"TCP connections: {tcp_count}")
        print(f"ESTABLISHED: {established}")
        print(f"TIME_WAIT: {time_wait}")
        
except Exception as e:
    print(f"Error getting connections: {e}")

# Память
mem = p.memory_info()
print(f"Memory RSS: {mem.rss / 1024 / 1024:.1f} MB")

# CPU
cpu = p.cpu_percent(interval=1)
print(f"CPU: {cpu}%")