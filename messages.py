"""
BitTorrent Peer Wire Protocol Messages

Message format: [4 bytes: length][1 byte: message_id][message_data]
All integers are big-endian (network byte order)
"""
import struct

# Message IDs
MSG_CHOKE = 0
MSG_UNCHOKE = 1
MSG_INTERESTED = 2
MSG_NOT_INTERESTED = 3
MSG_HAVE = 4
MSG_BITFIELD = 5
MSG_REQUEST = 6
MSG_PIECE = 7
MSG_CANCEL = 8

# Keep-alive message has length 0 (no message ID)
KEEP_ALIVE = b'\x00\x00\x00\x00'


def create_message(message_id, payload=b''):
    """
    Creates a BitTorrent protocol message.
    
    Args:
        message_id: int - Message ID (0-8)
        payload: bytes - Optional message payload
    
    Returns:
        bytes - Complete message: [length(4)][message_id(1)][payload]
    """
    length = 1 + len(payload)  # 1 byte for message_id + payload
    return struct.pack('>IB', length, message_id) + payload


def create_keep_alive():
    """Creates a keep-alive message (4 zero bytes)."""
    return KEEP_ALIVE


def create_choke():
    """Creates a choke message."""
    return create_message(MSG_CHOKE)


def create_unchoke():
    """Creates an unchoke message."""
    return create_message(MSG_UNCHOKE)


def create_interested():
    """Creates an interested message."""
    return create_message(MSG_INTERESTED)


def create_not_interested():
    """Creates a not interested message."""
    return create_message(MSG_NOT_INTERESTED)


def create_have(piece_index):
    """
    Creates a have message.
    
    Args:
        piece_index: int - Index of the piece the peer has
    
    Returns:
        bytes - Have message
    """
    payload = struct.pack('>I', piece_index)
    return create_message(MSG_HAVE, payload)


def create_request(piece_index, block_offset, block_length):
    """
    Creates a request message.
    
    Args:
        piece_index: int - Index of the piece to request
        block_offset: int - Offset within the piece (typically 0, 16384, 32768, etc.)
        block_length: int - Length of block to request (typically 16384 bytes)
    
    Returns:
        bytes - Request message
    """
    payload = struct.pack('>III', piece_index, block_offset, block_length)
    return create_message(MSG_REQUEST, payload)


def parse_message(data):
    """
    Parses a BitTorrent protocol message.
    
    Args:
        data: bytes - Raw message data starting with length field
    
    Returns:
        tuple: (message_id, payload, bytes_consumed) or None if incomplete
               message_id is None for keep-alive
    """
    if len(data) < 4:
        return None  # Not enough data for length field
    
    # Read length (4 bytes, big-endian)
    length = struct.unpack('>I', data[0:4])[0]
    
    # Keep-alive message
    if length == 0:
        return (None, b'', 4)
    
    # Check if we have the full message
    if len(data) < 4 + length:
        return None  # Message not complete yet
    
    # Read message ID (1 byte)
    message_id = data[4]
    
    # Read payload (rest of message)
    payload = data[5:5+length-1] if length > 1 else b''
    
    return (message_id, payload, 4 + length)


def parse_bitfield(payload):
    """
    Parses a bitfield message payload.
    
    Args:
        payload: bytes - Bitfield payload
    
    Returns:
        list of bool - List where index i is True if piece i is available
    """
    bitfield = []
    for byte in payload:
        for bit_pos in range(7, -1, -1):  # Most significant bit first
            bitfield.append(bool(byte & (1 << bit_pos)))
    return bitfield


def parse_have(payload):
    """
    Parses a have message payload.
    
    Args:
        payload: bytes - Have message payload (4 bytes)
    
    Returns:
        int - Piece index
    """
    if len(payload) != 4:
        raise ValueError(f"Have message payload must be 4 bytes, got {len(payload)}")
    return struct.unpack('>I', payload)[0]


def parse_piece(payload):
    """
    Parses a piece message payload.
    
    Args:
        payload: bytes - Piece message payload
    
    Returns:
        tuple: (piece_index, block_offset, block_data)
    """
    if len(payload) < 8:
        raise ValueError(f"Piece message payload too short: {len(payload)} bytes")
    
    piece_index = struct.unpack('>I', payload[0:4])[0]
    block_offset = struct.unpack('>I', payload[4:8])[0]
    block_data = payload[8:]
    
    return (piece_index, block_offset, block_data)


def parse_request(payload):
    """
    Parses a request message payload.
    
    Args:
        payload: bytes - Request message payload (12 bytes)
    
    Returns:
        tuple: (piece_index, block_offset, block_length)
    """
    if len(payload) != 12:
        raise ValueError(f"Request message payload must be 12 bytes, got {len(payload)}")
    
    piece_index, block_offset, block_length = struct.unpack('>III', payload)
    return (piece_index, block_offset, block_length)

