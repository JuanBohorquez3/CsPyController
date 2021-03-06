__author__ = 'jaisaacs'

###
# Serial interface for control of the Newport Vertical Stage
#
# Joshua A Isaacs 2016/11/3
#
#
###

import serial

class Newport():

    #ser_add = '' #'COM6'# Address of serial controller for stage
    motion_dict = dict(home = 'XH',pos = 'XR', moveAbs = 'XG ', setVel = 'XV ')

    minpos = -13700
    maxpos =  13700

    def __init__(self,comport):
        self.ser_add = comport
        self.ser = serial.Serial(self.ser_add)
        if self.ser.isOpen() == False:
            try:
                ser.open()
            except Exception as e:
                print e

            #Communication options
        self.ser.timeout = 1
        self.ser.xonxoff = True

        self.WriteThenPrint('COMOPT3')


    def WriteThenPrint(self,s):
        self.ser.write((s+'\n\r').encode('utf-8'))
        response = self.ser.readlines()
        for i in response:
            print i.rstrip()

    def WriteThenStore(self,s):
        self.ser.write((s+'\n\r').encode('utf-8'))
        response = self.ser.readlines()
        return response

    def home(self): self.WriteThenStore('XH')

    def setVelocity(self,vel): self.WriteThenStore('XV {}'.format(vel))

    def moveAbs(self,pos): self.WriteThenStore('XG {}'.format(pos))

    def moveAbsCheck(self,pos):
        '''
        Moves stage to position "pos" and acknowledges arrival with message
        :param pos:
        :return:
        '''
        output = self.WriteThenStore('XG {}'.format(pos))
        done = ''
        while done != 'XD':
            done = self.status()
            print('Status: {}\n'.format(done))
        print('Calibration: Complete!')

    def status(self): return self.WriteThenStore('XSTAT')[0].rstrip()[-2:]

    def whereAmI(self):
        output = self.WriteThenStore('XR')[1].rstrip()[2:]
        while output == '':
            output = self.WriteThenStore('XR')[1].rstrip()[2:]
        return float(output)

    def findCenter(self,side=-1):
        self.WriteThenStore('XF {}'.format(side))
        done = ''
        while done != 'XD':
            done = self.status()
            print('Status: {}\n'.format(done))
        print('Center: Found!')


    def calibrateStage(self):
        self.WriteThenStore('XAZ')
        done = ''
        while done != 'XD':
            done = self.status()
            print('Status: {}\n'.format(done))
        print('Calibration: Complete!')








