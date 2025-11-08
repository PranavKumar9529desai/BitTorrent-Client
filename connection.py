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
from piece_manager import get_saved_pieces, is_piece_complete


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


def exchange_messages(peer_socket, info_dict, timeout=30, pieces_dir='pieces', max_pieces_to_download=None):
    """
    Exchanges Peer Wire Protocol messages with a peer.
    
    Args:
        peer_socket: socket - Connected socket
        info_dict: dict - Torrent info dictionary (for piece length)
        timeout: int - Message timeout in seconds
        pieces_dir: str - Directory where pieces are saved
        max_pieces_to_download: int - Maximum pieces to download (None = all)
    
    Returns:
        dict - {'bitfield': list, 'pieces': dict} or None if failed
    """
    peer_socket.settimeout(timeout)
    buffer = b''
    bitfield = None
    unchoked = False
    pieces_received = {}  # {piece_index: {offset: data}}
    blocks_requested = {}  # {piece_index: set(offsets)} - Track requested blocks
    block_size = 16384  # 16 KB blocks
    max_concurrent_pieces = 5  # Download up to 5 pieces concurrently
    
    # Calculate piece length
    piece_length = info_dict.get('piece length', 262144)  # Default 256 KB
    pieces_data = info_dict.get('pieces', b'')
    if isinstance(pieces_data, bytes):
        num_pieces = len(pieces_data) // 20
    else:
        num_pieces = 0
    
    # Get already saved pieces
    saved_pieces = get_saved_pieces(pieces_dir)
    print(f"Starting message exchange (expecting {num_pieces} pieces, {piece_length} bytes each)")
    print(f"Each piece needs {piece_length // block_size} blocks of {block_size} bytes")
    if saved_pieces:
        print(f"Found {len(saved_pieces)} pieces already saved on disk")
    
    # Determine which pieces to download
    if max_pieces_to_download:
        pieces_to_download = min(max_pieces_to_download, num_pieces)
    else:
        pieces_to_download = num_pieces
    
    pieces_downloading = set()  # Track which pieces we're currently downloading
    pieces_completed = set(saved_pieces)  # Track completed pieces (including saved ones)
    
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
                        request_initial_blocks(peer_socket, bitfield, piece_length, num_pieces, 
                                             pieces_received, blocks_requested, pieces_downloading,
                                             pieces_completed, pieces_to_download, block_size)
                
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
                    
                    # Remove from requested set (we received it)
                    if piece_index in blocks_requested and block_offset in blocks_requested[piece_index]:
                        blocks_requested[piece_index].discard(block_offset)
                    
                    # Check if piece is now complete
                    if is_piece_complete(pieces_received, piece_index, piece_length):
                        if piece_index not in pieces_completed:
                            pieces_completed.add(piece_index)
                            pieces_downloading.discard(piece_index)
                            print(f"✓ Piece {piece_index} completed! ({len(pieces_completed)}/{pieces_to_download} pieces)")
                            
                            # Request next piece if we have room
                            if unchoked and bitfield and len(pieces_downloading) < max_concurrent_pieces:
                                request_next_available_piece(peer_socket, bitfield, piece_length, num_pieces,
                                                           pieces_received, blocks_requested, pieces_downloading,
                                                           pieces_completed, pieces_to_download, block_size)
                    else:
                        # Show progress for incomplete pieces (less verbose)
                        if len(pieces_received[piece_index]) % 4 == 0:  # Print every 4 blocks
                            blocks_received = len(pieces_received[piece_index])
                            print(f"Piece {piece_index}: {blocks_received} blocks received")
                    
                    # Check if we need to request more blocks for this piece
                    if unchoked and bitfield and bitfield[piece_index]:
                        request_next_blocks(peer_socket, piece_index, piece_length, num_pieces,
                                          pieces_received, blocks_requested, block_size)
                
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


def request_initial_blocks(peer_socket, bitfield, piece_length, num_pieces, 
                          pieces_received, blocks_requested, pieces_downloading,
                          pieces_completed, pieces_to_download, block_size=16384):
    """
    Requests initial blocks from first available pieces that peer has.
    
    Args:
        peer_socket: socket - Connected socket
        bitfield: list - List of booleans indicating available pieces
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary to store received pieces
        blocks_requested: dict - Dictionary to track requested blocks
        pieces_downloading: set - Set of piece indices currently being downloaded
        pieces_completed: set - Set of piece indices already completed
        pieces_to_download: int - Total number of pieces to download
        block_size: int - Size of each block to request (default 16 KB)
    """
    if not bitfield:
        return
    
    max_concurrent = 5  # Start with 5 pieces concurrently
    
    # Find pieces to download (not already completed, peer has them, not already downloading)
    for piece_index in range(min(pieces_to_download, len(bitfield))):
        if (piece_index not in pieces_completed and 
            piece_index not in pieces_downloading and
            bitfield[piece_index] and 
            len(pieces_downloading) < max_concurrent):
            
            # Initialize tracking
            if piece_index not in blocks_requested:
                blocks_requested[piece_index] = set()
            if piece_index not in pieces_received:
                pieces_received[piece_index] = {}
            
            # Request first block (offset 0)
            request_length = min(block_size, piece_length)
            request_msg = create_request(piece_index, 0, request_length)
            peer_socket.sendall(request_msg)
            blocks_requested[piece_index].add(0)
            pieces_downloading.add(piece_index)
            print(f"Requested piece {piece_index}, block 0 (offset 0, {request_length} bytes)")
            
            if len(pieces_downloading) >= max_concurrent:
                break


def request_next_available_piece(peer_socket, bitfield, piece_length, num_pieces,
                                 pieces_received, blocks_requested, pieces_downloading,
                                 pieces_completed, pieces_to_download, block_size=16384):
    """
    Requests the next available piece when a piece completes.
    
    Args:
        peer_socket: socket - Connected socket
        bitfield: list - List of booleans indicating available pieces
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary of received pieces
        blocks_requested: dict - Dictionary tracking requested blocks
        pieces_downloading: set - Set of pieces currently downloading
        pieces_completed: set - Set of completed pieces
        pieces_to_download: int - Total pieces to download
        block_size: int - Size of each block
    """
    if not bitfield:
        return
    
    # Find next piece to download
    for piece_index in range(min(pieces_to_download, len(bitfield))):
        if (piece_index not in pieces_completed and 
            piece_index not in pieces_downloading and
            bitfield[piece_index]):
            
            # Initialize tracking
            if piece_index not in blocks_requested:
                blocks_requested[piece_index] = set()
            if piece_index not in pieces_received:
                pieces_received[piece_index] = {}
            
            # Request first block
            request_length = min(block_size, piece_length)
            request_msg = create_request(piece_index, 0, request_length)
            peer_socket.sendall(request_msg)
            blocks_requested[piece_index].add(0)
            pieces_downloading.add(piece_index)
            print(f"Requested piece {piece_index}, block 0 (offset 0, {request_length} bytes)")
            break


def request_next_blocks(peer_socket, piece_index, piece_length, num_pieces,
                        pieces_received, blocks_requested, block_size=16384):
    """
    Continues requesting more blocks for a piece as blocks are received.
    
    Args:
        peer_socket: socket - Connected socket
        piece_index: int - Index of piece to continue requesting
        piece_length: int - Length of each piece
        num_pieces: int - Total number of pieces
        pieces_received: dict - Dictionary of received blocks
        blocks_requested: dict - Dictionary tracking requested blocks
        block_size: int - Size of each block
    """
    if piece_index not in pieces_received:
        return
    
    # Calculate how many blocks this piece needs
    if piece_index == num_pieces - 1:
        # Last piece might be smaller - we'll calculate from total size
        # For now, use piece_length (we'll handle last piece specially later)
        blocks_needed = (piece_length + block_size - 1) // block_size
    else:
        blocks_needed = piece_length // block_size
    
    # Get blocks we already have
    received_offsets = set(pieces_received[piece_index].keys())
    
    # Find next block to request
    for block_num in range(blocks_needed):
        offset = block_num * block_size
        
        # Skip if we already have this block
        if offset in received_offsets:
            continue
        
        # Skip if we already requested this block
        if piece_index in blocks_requested and offset in blocks_requested[piece_index]:
            continue
        
        # Calculate request length (last block might be smaller)
        remaining = piece_length - offset
        request_length = min(block_size, remaining)
        
        # Request this block
        request_msg = create_request(piece_index, offset, request_length)
        peer_socket.sendall(request_msg)
        
        # Track that we requested it
        if piece_index not in blocks_requested:
            blocks_requested[piece_index] = set()
        blocks_requested[piece_index].add(offset)
        
        print(f"Requested piece {piece_index}, block {block_num} (offset {offset}, {request_length} bytes)")
        break  # Request one block at a time


def connect_to_peer(peer, info_hash, peer_id, info_dict, pieces_dir='pieces', max_pieces=None):
    """
    Complete peer connection flow: TCP -> Handshake -> Messages.
    
    Args:
        peer: dict - {'ip': str, 'port': int}
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
        pieces_dir: str - Directory to save pieces
        max_pieces: int - Maximum pieces to download (None = all)
    
    Returns:
        dict - Results from message exchange or None
    """
    # Step 1: Connect and handshake
    peer_socket, peer_peer_id = connect_and_handshake(peer, info_hash, peer_id)
    if not peer_socket:
        return None
    
    try:
        # Step 2: Exchange messages
        result = exchange_messages(peer_socket, info_dict, timeout=60, 
                                 pieces_dir=pieces_dir, max_pieces_to_download=max_pieces)
        return result
    finally:
        peer_socket.close()
        print("Connection closed")


def connect(peer_list, info_hash, peer_id, info_dict, pieces_dir='pieces', max_pieces=None):
    """
    Attempts to connect to multiple peers.
    
    Args:
        peer_list: list - List of peer dicts
        info_hash: bytes - 20-byte info hash
        peer_id: bytes - 20-byte peer ID
        info_dict: dict - Torrent info dictionary
        pieces_dir: str - Directory to save pieces
        max_pieces: int - Maximum pieces to download (None = all)
    """
    for peer in peer_list:
        print(f"\n{'='*60}")
        result = connect_to_peer(peer, info_hash, peer_id, info_dict, pieces_dir, max_pieces)
        if result:
            print(f"Successfully connected to {peer['ip']}:{peer['port']}")
            return result
        print(f"Failed to connect to {peer['ip']}:{peer['port']}")
    
    return None

