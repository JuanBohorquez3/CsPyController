#TCP.py
#author: Martin Lichtman
#created = 2013.08.02
#modified >= 2013.08.02

#This module bundles the TCP message passing protocol defined for the Cesium project.

#Messages begin with 'MESG' followed by a 4 byte unsigned long int that gives the length of the remainder of the message.

#The class CsSock inherets from socket.socket, and makes it easier to open up the type of socket we use, and then send or receive
#a message with the correct format.


import socket, struct, logging, numpy, threading
logger = logging.getLogger(__name__)
logging.basicConfig(format='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y/%m/%d %H:%M:%S', level=logging.DEBUG)
from cs_errors import PauseError

def prefixLength(txt):
    length=len(txt)
    if length>=4294967296: #2**32
        logger.error('message is too long, size = '+str(length)+' bytes')
        raise PauseError
    return struct.pack("!L",length)+txt

def sendmsg(sock,msgtxt):
    message='MESG'+prefixLength(msgtxt)
    print 'send: {}'.format(message)
    try:
        sock.sendall(message)
    except Exception as e:
        logger.error('Error sending message: '+str(e))
        return

def receive(sock):
    #every message should start with 'MESG'
    try:
        header = sock.recv(4)
        print 'header: {}'.format(header)
    except Exception as e:
        logger.error('Error trying to receive message header: '+str(e))
        raise PauseError
    if not header:
        #buffer is empty, no message yet
        return
    if header!='MESG':
        logger.error('incorrectly formatted message does not being with "MESG".  Draining TCP input buffer')
        #Clear the buffer so we aren't in the middle of a message
        #TODO: There is some risk that this will result in lost messages, if
        #a good one comes into the buffer before the bad one is cleared. We
        #we may not want to do this.
        while 1:
            data = sock.recv(4096)
            print 'draining:{}'.format(data)
            if not data: break

    #the next part of the message is a 4 byte unsigned long interger that contains the length (in bytes) of the rest of the message
    try:
        datalenmsg=sock.recv(4)
    except Exception as e:
        logger.warning('exception trying to read 4 byte message length')
        raise PauseError
    print 'data length msg: {}'.format(datalenmsg)
    try:
        datalen=struct.unpack("!L", datalenmsg)[0]
    except Exception as e:
        logger.warning('incorrectly formatted message: does not have 4 byte unsigned long for length. '+str(e))
        raise PauseError
    print 'data length: {}'.format(datalen)
    
    #now get the real data
    try:
        rawdata=sock.recv(datalen)
        print 'rawdata: {}'.format(rawdata)
        remaining=datalen-len(rawdata)
        while remaining>0: #repeat until we've got all the data
            logger.info('waiting for more data: '+str(len(rawdata))+'/'+str(datalen))
            rawdata+=sock.recv(remaining)
            print 'rawdata: {}'.format(rawdata)
            remaining=datalen-len(rawdata)
    except Exception as e:
        logger.error('error while trying to read message data:'+str(e))
        raise PauseError
    #check size
    if len(rawdata)!=datalen:
        logger.error('incorrect message size received')
        return
    #if we get here, we have gotten data of the right size
    print 'rawdata: {}'.format(rawdata)
    return rawdata
    #do something like this for data packets, but not here:  data=struct.unpack("!{}d".format(datalen/8),rawdata)

class CsSock(socket.socket):
    def __init(self):
        super(CsSock,self).__init__(socket.AF_INET, socket.SOCK_STREAM)
    
        

class CsClientSock(CsSock):
    #if provided, parent is used as a callback to set parent.connected
    def __init__(self,addressString,portNumber,parent=None):
        self.parent=parent
        super(CsClientSock,self).__init__()
        print 'connecting to {} port {}'.format(addressString,portNumber)
        try:
            self.connect((addressString,portNumber))
            self.setblocking(0) #wait until after we are connected, and then set the socket to be non-blocking
        except Exception as e:
            logger.error('Error while opening socket: '+str(e))
            self.close()
            raise PauseError
        else:
            if self.parent is not None:
                self.parent.connected=True
    
    def sendmsg(self,msgtxt):
        #reference the common message format
        sendmsg(self,msgtxt)
    
    def receive(self):
        #reference the common message format
        return receive(self)
    
    def close(self):
        if self.parent is not None:
            self.parent.connected=False
            self.parent.initialized=False
        self.shutdown(socket.SHUT_RDWR)
        super(CsClientSock,self).close()
    
    def parsemsg(self,msg):
        '''Take apart an incoming message that is composed of a sequence of (namelength,name,datalength,data) sets.
        These are then stored in a dictionary under name:data.'''
        l=len(msg)
        i=0
        result={}
        while i<l:
            L=struct.unpack('!L',msg[i:i+4])[0]
            i+=4
            name=msg[i:i+L]
            i+=L
            L=struct.unpack('!L',msg[i:i+4])[0]
            i+=4
            data=msg[i:i+L]
            i+=L
            result.update([(name,data)])
        return result

class CsServerSock(CsSock):
    
    def closeConnection(self):
        if self.connection is not None:
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
    
    def sendmsg(self,msgtxt):
        #reference the common message format
        sendmsg(self.connection,msgtxt)
    
    def receive(self):
        #reference the common message format
        return receive(self.connection)

    def __init__(self,portNumber):
        super(CsServerSock,self).__init__()
        self.portNumber=portNumber
        # Bind the socket to the port given
        server_address = ('', portNumber)
        try:
            self.bind(server_address)
        except Exception as e:
            logger.warning('error on CsServerSock.bind({}):\n{}'.format(server_address,str(e)))
            raise PauseError
        logger.info('server starting up on %s port %s' % self.getsockname())
        threading.Thread(target=self.readLoop).start()
    
    def makemsg(self,name,data):
        return prefixLength(name)+prefixLength(data)
    
    def readLoop(self):
        self.listen(0) #the 0 means do not listen to any backlogged connections
        while True:
            logger.info('waiting for a connection')
            #the sock is blocking so it will wait for a connection
            try:
                self.connection, client_address = self.accept()
                logger.info('client connected: '+str(client_address))
            except:
                logger.info('error in CsServerSock self.accept()')
                self.closeConnection()
                continue
            while True:
                try:
                    data=self.receive()
                except:
                    logger.info('error in CsServerSock receive')
                    self.closeConnection()
                    raise PauseError
                print 'received: {}'.format(data)
                if (data is not None):
                    if data.startswith('measure'):
                        #create some dummy data 16-bit 512x512
                        rows=3; columns=3; bytes=1; signed=''; highbit=2**(8*bytes);
                        testdata=numpy.random.randint(0,highbit,(rows,columns))
                        #turn the image array into a long string composed of 2 bytes for each number
                        #first create a struct object, because reusing the same object is more efficient
                        myStruct=struct.Struct('!H') #'!H' indicates unsigned short (2 byte) integers
                        testdatamsg=''.join([myStruct.pack(t) for t in testdata.flatten()])
                        msg=self.makemsg('Hamamatsu/rows',str(rows))+self.makemsg('Hamamatsu/columns',str(columns))+self.makemsg('Hamamatsu/bytes',str(bytes))+self.makemsg('Hamamatsu/signed',str(signed))+self.makemsg('Hamamatsu/shots/0',testdatamsg)
                        
                        try:
                            self.sendmsg(msg)
                        except:
                            logger.info('error in CsServerSock sendmsg')
                            self.closeConnection()
                            raise PauseError
                    else:
                        logger.info('bad command received: {}'.format(data))