# Using builtin sockets for Tcp connections
import socket
 # {'ip': '2409:40d1:101a:3fca:d99d:6b0e:9fd7:1650', 'port': 6889}
peer = {'ip': '2409:40d1:101a:3fca:d99d:6b0e:9fd7:1650', 'port': 6889}

def connect(peer_list):
    connection_timemout = 10 # seconds
    for peer in peer_list :
        peer_socket = None # intialize variable 
        try :
            print(f"Connecting to the {peer['ip']} and port {peer['port']}")

            peer_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)

            peer_socket.settimeout(connection_timemout)

            peer_socket.connect(( peer['ip'], peer['port'] ))

            print(f"connection is sucessfull")

        except socket.timeout:
            print(f"Connection attempt timed out after {connection_timemout} seconds. ⏳")
        except socket.error as e:
            print(f"Connection failed")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

        finally:
            if peer_socket:
                print("Closing the socket.")
                peer_socket.close()
            else:
                print("Socket was not created or connected.")

