#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 
# --------------
# Packet Encoder
# --------------
# Copyright 2016 Carleton University.
# Authors: Michel Barbeau
# Version: November 14, 2016
# 
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
# 
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this software; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
# 
from gnuradio import gr, digital
from gnuradio import blocks
from gnuradio.digital import packet_utils
import gnuradio.gr.gr_threading as _threading
import sys

##payload length in bytes
DEFAULT_PAYLOAD_LEN = 512

##how many messages in a queue
DEFAULT_MSGQ_LIMIT = 2

##threshold for unmaking packets
DEFAULT_THRESHOLD = 12

##################################################
## Packet Encoder
##################################################
class _packet_encoder_thread(_threading.Thread):

    def __init__(self, msgq, payload_length, send):
        self._msgq = msgq
        self._payload_length = payload_length
        self._send = send
        _threading.Thread.__init__(self)
        self.setDaemon(1)
        self.keep_running = True
        self.start()

    def run(self):
        sample = '' #residual sample
        while self.keep_running:
            msg = self._msgq.delete_head() #blocking read of message queue
            #sample = sample + msg.to_string() #get the body of the msg as a string
            sys.stderr.write("message size is %s\n" % len(sample))
            #while len(sample) >= self._payload_length:
            #    payload = sample[:self._payload_length]
            #    sample = sample[self._payload_length:]
            #    self._send(payload)
            sample = msg.to_string()
            self._send(sample)

class packet_encoder_source(gr.hier_block2):
    """
    Hierarchical block for wrapping packet-based modulators.
    """

    def __init__(self, samples_per_symbol, bits_per_symbol, preamble='', access_code='', pad_for_usrp=True):
        """
        packet_mod constructor.

        Args:
            samples_per_symbol: number of samples per symbol
            bits_per_symbol: number of bits per symbol
            preamble: string of ascii 0's and 1's
            access_code: AKA sync vector
            pad_for_usrp: If true, packets are padded such that they end up a multiple of 128 samples
        """
        #setup parameters
        self._samples_per_symbol = samples_per_symbol
        self._bits_per_symbol = bits_per_symbol
        self._pad_for_usrp = pad_for_usrp
        if not preamble: #get preamble
            preamble = packet_utils.default_preamble
        if not access_code: #get access code
            access_code = packet_utils.default_access_code
        if not packet_utils.is_1_0_string(preamble):
            raise ValueError, "Invalid preamble %r. Must be string of 1's and 0's" % (preamble,)
        if not packet_utils.is_1_0_string(access_code):
            raise ValueError, "Invalid access_code %r. Must be string of 1's and 0's" % (access_code,)
        self._preamble = preamble
        self._access_code = access_code
        self._pad_for_usrp = pad_for_usrp
        #create blocks
        msg_source = blocks.message_source(gr.sizeof_char, DEFAULT_MSGQ_LIMIT)
        self._msgq_out = msg_source.msgq()
        #initialize hier2
        gr.hier_block2.__init__(
            self,
            "packet_encoder",
            gr.io_signature(0, 0, 0), # Input signature
            gr.io_signature(1, 1, gr.sizeof_char) # Output signature
        )
        #connect
        self.connect(msg_source, self)

    def send_pkt(self, payload):
        """
        Wrap the payload in a packet and push onto the message queue.

        Args:
            payload: string, data to send
        """
        packet = packet_utils.make_packet(
            payload,
            self._samples_per_symbol,
            self._bits_per_symbol,
            self._preamble,
            self._access_code,
            self._pad_for_usrp,
	    0,
	    True,
            False
        )
        msg = gr.message_from_string(packet)
        self._msgq_out.insert_tail(msg)

##################################################
## Packet Mod for OFDM Mod and Packet Encoder
##################################################
class packet_encoder(gr.hier_block2):
    """
    Hierarchical block for wrapping packet source block.
    """

    def __init__(self, samples_per_symbol, bits_per_symbol, preamble='', access_code='', pad_for_usrp=True, payload_length=0):
	
	packet_source=packet_encoder_source(samples_per_symbol, bits_per_symbol, preamble, access_code, pad_for_usrp)


        if not payload_length: #get payload length
            payload_length = DEFAULT_PAYLOAD_LEN

	self._item_size_in = gr.sizeof_char
        if payload_length%self._item_size_in != 0:  #verify that packet length is a multiple of the stream size
            raise ValueError, 'The payload length: "%d" is not a mutiple of the stream size: "%d".'%(payload_length, self._item_size_in)
        #initialize hier2
        gr.hier_block2.__init__(
            self,
            "ofdm_mod",
            gr.io_signature(1, 1, self._item_size_in), # Input signature
            gr.io_signature(1, 1, packet_source.output_signature().sizeof_stream_item(0)) # Output signature
        )
        #create blocks
        msgq = gr.msg_queue(DEFAULT_MSGQ_LIMIT)
        msg_sink = blocks.message_sink(self._item_size_in, msgq, False) #False -> blocking
        #connect
        self.connect(self, msg_sink)
        self.connect(packet_source, self)
        #start thread
        _packet_encoder_thread(msgq, payload_length, packet_source.send_pkt)
