#!/usr/bin/env python
"""
domoticz-emmeti-eq2021 hot water heat pump plugin for Domoticz.
Author: Paolo Subiaco https://github.com/CreasolTech
Based on https://github.com/CreasolTech/domoticz-emmeti-mirai plugin for Domoticz
Tested with Emmeti Mirai EQ2021 (Modbus, 9600bps, even parity, slave addr=3)

THIS SOFTWARE COMES WITH ABSOLUTE NO WARRANTY. USE AT YOUR OWN RISK!

Requirements:
    1.python module minimalmodbus -> http://minimalmodbus.readthedocs.io/en/master/
        (pi@raspberrypi:~$ sudo pip3 install minimalmodbus)
    2.Communication module Modbus USB to RS485 converter module
"""
"""
<plugin key="EmmetiMiraiEQ2021" name="Emmeti-Mirai EQ2021 hot water heatpump" version="1.0" author="CreasolTech" externallink="https://github.com/CreasolTech/domoticz-emmeti-eq2021">
    <description>
        <h2>Domoticz Emmeti EQ 2021 hot water heat pump - Version 1.0</h2>
        Get some values from the heat pump, and permit to set the set point of hot water, to enable the heat pump on/off<br/>
        <b>THIS SOFTWARE COMES WITH ABSOLUTE NO WARRANTY: USE AT YOUR OWN RISK!</b>
    </description>
    <params>
        <param field="SerialPort" label="Modbus Port" width="200px" required="true" default="/dev/ttyUSB0" />
        <param field="Mode1" label="Baud rate" width="40px" required="true" default="9600"  />
        <param field="Mode2" label="Heat pump address" width="40px" required="true" default="3" />
        <param field="Mode3" label="Poll interval">
            <options>
                <option label="10 seconds" value="10" />
                <option label="20 seconds" value="20" />
                <option label="30 seconds" value="30" default="true" />
                <option label="60 seconds" value="60" />
                <option label="120 seconds" value="120" />
                <option label="240 seconds" value="240" />
            </options>
        </param>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>

"""

import minimalmodbus    #v2.1.1
import Domoticz         #tested on Python 3.9.2 in Domoticz 2021.1 and 2023.1


LANGS=[ "en", "it" ] # list of supported languages, in DEVS dict below
DEVADDR=0   #field corresponding to Modbus address in the DEVS dict
DEVUNIT=1
DEVTYPE=2
DEVSUBTYPE=3
DEVSWITCHTYPE=4
DEVOPTIONS=5
DEVIMAGE=6
DEVLANG=7  # item in the DEVS list where the first language starts 

DEVS={ #topic:                Modbus, Unit,Type,Sub,swtype, Options, Image,  "en name", "it name"  ...other languages should follow  ],
    "SP_HOTWATER":          [ 1104,     1,242,1,0,  {'ValueStep':'0.5', ' ValueMin':'10', 'ValueMax':'60', 'ValueUnit':'°C'},   None,  "SetPoint Hot Water", "Termostato ACS"    ],
    "SP_DIFF":              [ 1106,     2,242,1,0,  {'ValueStep':'0.5', ' ValueMin':'1', 'ValueMax':'20', 'ValueUnit':'°C'},    None,  "SetPoint-TempLow to activate", "SetPoin-TempLow per attivare", "Termostato uscita per ACS" ],
    "SP_RESISTOR_DELAY":    [ 1109,     3,242,1,0,  {'ValueStep':'5', ' ValueMin':'0', 'ValueMax':'450', 'ValueUnit':'min.'},   None,  "Resistor start delay", "Ritardo acc. resistenza"  ],
    "TEMP_WATER_BOTTOM":    [ 2020,     4, 80,5,0,  None,           None,   "Temp tank bottom",     "Temp bollitore in basso"     ],
    "TEMP_WATER_TOP":       [ 2021,     5, 80,5,0,  None,           None,   "Temp tank top",        "Temp bollitore in alto"     ],
    "TEMP_AIR_IN":          [ 2019,     6,80,5,0,   None,           None,   "Temp air inlet",       "Temp aria ingresso"      ],
    "TEMP_AIR_OUT":         [ 2023,     7,80,5,0,   None,           None,   "Temp air outlet",      "Temp aria uscita"   ],
    "TEMP_COIL":            [ 2022,     8,80,5,0,   None,           None,   "Temp coil",            "Temp scambiatore"   ],
}

def value2temp(value):
    """ Convert value returned by Modbus to a temperature """
    return (value-60)*0.5   # 60 = 0°C, 160 = 50°C

def temp2value(temp):
    """ Convert a temperature to a Modbus value for this heat pump """
    return int(temp*2)+60

class BasePlugin:
    def __init__(self):
        self.rs485 = ""
        return

    def onStart(self):
        devicecreated = []
        Domoticz.Log("Starting Emmeti-EQ2021 plugin")
        self.pollTime=30 if Parameters['Mode3']=="" else int(Parameters['Mode3'])
        self.heartbeat=self.pollTime if self.pollTime<=30 else 30   # heartbeat must be <=30 or a warning will be written in the log
        self.elapsedTime=0
        self.heartbeatnow=self.heartbeat        # used to track any temp modification of the heartbeat
        Domoticz.Heartbeat(self.heartbeatnow)
        self.runInterval = 1
        self._lang=Settings["Language"]
        # check if language set in domoticz exists
        if self._lang in LANGS:
            self.lang=DEVLANG+LANGS.index(self._lang)
        else:
            Domoticz.Log(f"Language {self._lang} does not exist in dict DEVS, inside the domoticz-emmeti-mirai plugin, but you can contribute adding it ;-) Thanks!")
            self._lang="en"
            self.lang=DEVLANG # default: english text

        # Check that all devices exist, or create them
        for i in DEVS:
            if DEVS[i][DEVUNIT] not in Devices:
                Options=DEVS[i][DEVOPTIONS] if DEVS[i][DEVOPTIONS] else {}
                Image=DEVS[i][DEVIMAGE] if DEVS[i][DEVIMAGE] else 0
                Domoticz.Log(f"Creating device {i}, Name={DEVS[i][self.lang]}, Unit={DEVS[i][DEVUNIT]}, Type={DEVS[i][DEVTYPE]}, Subtype={DEVS[i][DEVSUBTYPE]}, Switchtype={DEVS[i][DEVSWITCHTYPE]} Options={Options}, Image={Image}")
                Domoticz.Device(Name=DEVS[i][self.lang], Unit=DEVS[i][DEVUNIT], Type=DEVS[i][DEVTYPE], Subtype=DEVS[i][DEVSUBTYPE], Switchtype=DEVS[i][DEVSWITCHTYPE], Options=Options, Image=Image, Used=1).Create()

        self.rs485 = minimalmodbus.Instrument(Parameters["SerialPort"], int(Parameters["Mode2"]))
        self.rs485.serial.baudrate = Parameters["Mode1"]
        self.rs485.serial.bytesize = 8
        self.rs485.serial.parity = minimalmodbus.serial.PARITY_EVEN
        self.rs485.serial.stopbits = 1
        self.rs485.serial.timeout = 0.2
        self.rs485.serial.exclusive = True # Fix From Forum Member 'lost'
        self.rs485.debug = True
        self.rs485.mode = minimalmodbus.MODE_RTU
        self.rs485.close_port_after_each_call = True

    def onStop(self):
        Domoticz.Log("Stopping Emmeti-EQ2021 plugin")

    def onHeartbeat(self):
        self.elapsedTime+=self.heartbeatnow
        if self.elapsedTime<self.pollTime:
            return
        self.elapsedTime=0
        
        errors=0

        startaddr=2019
        try:    #                          addr #regs   fc  
            values=self.rs485.read_registers(startaddr, 5,     3)
        except:
            Domoticz.Log(f"Error connecting to heat pump by Modbus, reading registers startaddr-2023")
            errors+=1
        else:
            item="TEMP_AIR_IN"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="TEMP_AIR_OUT"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="TEMP_COIL"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="TEMP_WATER_BOTTOM"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="TEMP_WATER_TOP"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

        startaddr=1104
        try:    #                          addr #regs   fc  
            values=self.rs485.read_registers(startaddr, 6,     3)
        except:
            Domoticz.Log(f"Error connecting to heat pump by Modbus, reading registers 1104-1109")
            errors+=1
        else:
            item="SP_HOTWATER"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="SP_DIFF"
            value=value2temp(values[DEVS[item][DEVADDR]-startaddr]) 
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")

            item="SP_RESISTOR_DELAY"
            value=values[DEVS[item][DEVADDR]-startaddr]*5
            sValue=str(value); nValue=0
            Devices[DEVS[item][DEVUNIT]].Update(nValue=nValue, sValue=sValue)
            if Parameters["Mode6"] == 'Debug':
                Domoticz.Log(f"{item}, Addr={DEVS[item][DEVADDR]}, nValue={nValue}, sValue={sValue}")


        self.rs485.serial.close()  #  Close that door !
        if errors:
            Domoticz.Log(f"Increase heartbeat to avoid error in case of multiple access to the same serial port")
            self.heartbeatnow+=1
            Domoticz.Heartbeat(self.heartbeatnow)
        else: #no errors
            if self.heartbeatnow!=self.heartbeat:
                Domoticz.Debug("Restore previous heartbeat value")
                self.heartbeatnow=self.heartbeat
                Domoticz.Heartbeat(self.heartbeatnow)


    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Log(f"Command for {Devices[Unit].Name}: Unit={Unit}, Command={Command}, Level={Level}")

        for i in DEVS:  # Find the index of DEVS
            if DEVS[i][DEVUNIT]==Unit:
                nValue=int(Level)
                sValue=str(Level)
                if DEVS[i][DEVADDR]<2000:  # Addresses above 2000 are read-only, in EMMETI EQxxxx
                    if i=='SP_RESISTOR_DELAY':
                        value=int(Level/5)    # 5 minutes step
                    else:
                        value=temp2value(Level)
                    self.WriteRS485(DEVS[i][DEVADDR], value)
                    Devices[Unit].Update(nValue=nValue, sValue=sValue)
                break


#        Devices[Unit].Refresh()

    def WriteRS485(self, Register, Value):
            try:
                 self.rs485.write_register(Register, Value, 0, 6, False)

                 self.rs485.serial.close()
            except:
                Domoticz.Log("Error writing to heat pump Modbus");


global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug("'" + x + "':'" + str(Parameters[x]) + "'")
            Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return


