"""
BitTorrent Peer Connection Handler

Handles TCP connection, handshake, and Peer Wire Protocol message exchange.
"""
import socket
import struct
from handshake import construct_handshake, validate_handshake
from messages import (
    create_interested, create_request, parse_message, parse_bitfield,
    parse_piece, MSG_BITFIELD, MSG_UNCHOKE, MSG_PIECE, MSG_CHOKE
)


def detect_ip_family(ip_address):
    """
    Detects if an IP address is IPv4 or IPv6.
    
    Args:
        ip_address: str - IP address string
    
    Returns:
        int - socket.AF_INET or socket.AF_INET6
    """
    if ':' in ip_address:
        return socket.AF_INET6
    else:
        return socket.AF_INET


def receive_exact(sock, length, timeout=30):
    """
    Receives exactly 'length' bytes from socket.
    
    Args:
        sock: socket - Socket to receive from
        length: int - Number of bytes to receive
        timeout: int - Timeout in seconds
    
    Returns:
        bytes - Received data, or None if incomplete/timeout
    """
    sock.settimeout(timeout)
    data = b''
    while len(data) < length:
        try:
            chunk = sock.recv(length - len(data))
            if not chunk:
                return None  # Connection closed
            data += chunk
        except socket.timeout:
            return None
    return data


def connect_and_handshake(peer, info_hash, peer_id, timeout=10):
    """
    Connects to a peer, performs handshake, and returns the socket if successful.
    
    Args:
        peer: dict - {'ip': str, 'port': int}
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        timeout: int - Connection timeout in seconds
    
    Returns:
        tuple: (socket, peer_peer_id) if successful, (None, None) if failed
    """
    peer_socket = None
    ip_family = detect_ip_family(peer['ip'])
    
    try:
        print(f"Connecting to {peer['ip']}:{peer['port']}")
        
        # Create socket
        peer_socket = socket.socket(ip_family, socket.SOCK_STREAM)
        peer_socket.settimeout(timeout)
        
        # TCP connection
        peer_socket.connect((peer['ip'], peer['port']))
        print(f"TCP connection established")
        
        # Send handshake
        handshake_msg = construct_handshake(info_hash, peer_id)
        peer_socket.sendall(handshake_msg)
        print("Handshake sent")
        
        # Receive handshake response
        handshake_response = receive_exact(peer_socket, 68, timeout)
        if not handshake_response:
            print("Failed to receive handshake response")
            return None, None
        
        # Validate handshake
        is_valid, peer_peer_id = validate_handshake(handshake_response, info_hash)
        if not is_valid:
            print("Handshake validation failed - wrong torrent")
            return None, None
        
        print(f"Handshake successful! Peer ID: {peer_peer_id.hex()[:8]}...")
        return peer_socket, peer_peer_id
        
    except socket.timeout:
        print(f"Connection/handshake timeout")
        return None, None
    except socket.error as e:
        print(f"Connection failed: {e}")
        return None, None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None, None


def exchange_messages(peer_socket, info_dict, timeout=30):
    """
    Exchanges Peer Wire Protocol messages with a peer.
    
    Args:
        peer_socket: socket - Connected socket
        info_dict: dict - Torrent info dictionary (for piece length)
        timeout: int - Message timeout in seconds
    
    Returns:
        dict - {'bitfield': list, 'pieces': dict} or None if failed
    """
    peer_socket.settimeout(timeout)
    buffer = b''
    bitfield = None
    unchoked = False
    pieces_received = {}  # {piece_index: {offset: data}}
    
    # Calculate piece length
    piece_length = info_dict.get('piece length', 262144)  # Default 256 KB
    pieces_data = info_dict.get('pieces', b'')
    if isinstance(pieces_data, bytes):
        num_pieces = len(pieces_data) // 20
    else:
        num_pieces = 0
    
    print(f"Starting message exchange (expecting {num_pieces} pieces)")
    
    try:
        # Send interested message
        interested_msg = create_interested()
        peer_socket.sendall(interested_msg)
        print("Sent INTERESTED message")
        
        # Message exchange loop
        while True:
            # Read data into buffer
            try:
                data = peer_socket.recv(4096)
                if not data:
                    print("Connection closed by peer")
                    break
                buffer += data
            except socket.timeout:
                print("Timeout waiting for messages")
                break
            
            # Process all complete messages in buffer
            while True:
                result = parse_message(buffer)
                if result is None:
                    break  # Incomplete message, wait for more data
                
                message_id, payload, bytes_consumed = result
                buffer = buffer[bytes_consumed:]
                
                # Handle keep-alive
                if message_id is None:
                    continue
                
                # Handle bitfield
                if message_id == MSG_BITFIELD:
                    bitfield = parse_bitfield(payload)
                    available_pieces = sum(bitfield)
                    print(f"Received BITFIELD: {available_pieces}/{num_pieces} pieces available")
                
                # Handle unchoke
                elif message_id == MSG_UNCHOKE:
                    unchoked = True
                    print("Received UNCHOKE - can now request pieces!")
                    
                    # Start requesting pieces if we have bitfield
                    if bitfield:
                        request_pieces(peer_socket, bitfield, piece_length, num_pieces, pieces_received)
                
                # Handle choke
                elif message_id == MSG_CHOKE:
                    unchoked = False
                    print("Received CHOKE - peer stopped sending data")
                
                # Handle piece
                elif message_id == MSG_PIECE:
                    piece_index, block_offset, block_data = parse_piece(payload)
                    if piece_index not in pieces_received:
                        pieces_received[piece_index] = {}
                    pieces_received[piece_index][block_offset] = block_data
                    print(f"Received PIECE {piece_index} block at offset {block_offset} ({len(block_data)} bytes)")
                
                else:
                    print(f"Received message ID: {message_id}")
        
        return {
            'bitfield': bitfield,
            'pieces': pieces_received
        }
        
    except Exception as e:
        print(f"Error in message exchange: {e}")
        import traceback
        traceback.print_exc()
        return None


def request_pieces(peer_socket, bitfield, piece_length, num_pieces, pieces_received, block_size=16384):
    """
    Requests pieces from peer based on bitfield.
    
    Args:
        peer_socket: socket - Connected socket
        bitfield: list - List of booleans indicating available pieces
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary to store received pieces
        block_size: int - Size of each block to request (default 16 KB)
    """
    if not bitfield:
        return
    
    # Request first few pieces that peer has
    requested = 0
    max_concurrent = 5  # Don't request too many at once
    
    for piece_index in range(min(num_pieces, len(bitfield))):
        if bitfield[piece_index] and requested < max_concurrent:
            # Request first block of this piece
            # Note: Last piece might be smaller, but we'll handle that when receiving
            request_length = min(block_size, piece_length)
            request_msg = create_request(piece_index, 0, request_length)
            peer_socket.sendall(request_msg)
            print(f"Requested piece {piece_index}, block 0 ({request_length} bytes)")
            requested += 1
            
            if requested >= max_concurrent:
                break


def connect_to_peer(peer, info_hash, peer_id, info_dict):
    """
    Complete peer connection flow: TCP -> Handshake -> Messages.
    
    Args:
        peer: dict - {'ip': str, 'port': int}
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
    
    Returns:
        dict - Results from message exchange or None
    """
    # Step 1: Connect and handshake
    peer_socket, peer_peer_id = connect_and_handshake(peer, info_hash, peer_id)
    if not peer_socket:
        return None
    
    try:
        # Step 2: Exchange messages
        result = exchange_messages(peer_socket, info_dict)
        return result
    finally:
        peer_socket.close()
        print("Connection closed")


def connect(peer_list, info_hash, peer_id, info_dict):
    """
    Attempts to connect to multiple peers.
    
    Args:
        peer_list: list - List of peer dicts
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
    """
    for peer in peer_list:
        print(f"\n{'='*60}")
        result = connect_to_peer(peer, info_hash, peer_id, info_dict)
        if result:
            print(f"Successfully connected to {peer['ip']}:{peer['port']}")
            return result
        print(f"Failed to connect to {peer['ip']}:{peer['port']}")
    
    return None

