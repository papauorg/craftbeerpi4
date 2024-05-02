import logging
import os
import shutil
import pkgutil
import psutil
import pathlib
import json
import aiohttp
from voluptuous.schema_builder import message
from cbpi.api.dataclasses import NotificationAction, NotificationType
from cbpi.api.base import CBPiBase
from cbpi.api.config import ConfigType
from cbpi.api import *
import zipfile
import socket
import importlib
from tabulate import tabulate
from datetime import datetime, timedelta

try:
    from systemd import journal
    systemd_available=True
except Exception:
    logger.warning("Failed to load systemd library. logfile download not available")
    systemd_available=False

class SystemController:

    def __init__(self, cbpi):
        self.cbpi = cbpi
        self.service = cbpi.actor
        self.logger = logging.getLogger(__name__)

        self.cbpi.app.on_startup.append(self.check_for_update)


    async def check_for_update(self, app):
        pass

    async def restart(self):
        logging.info("RESTART")
        os.system('systemctl reboot') 
        pass

    async def shutdown(self):
        logging.info("SHUTDOWN")
        os.system('systemctl poweroff') 
        pass

    async def backupConfig(self):
        output_filename = "cbpi4_config"
        dir_name = pathlib.Path(self.cbpi.config_folder.get_file_path(''))
        shutil.make_archive(output_filename, 'zip', dir_name)

    async def plugins_list(self): 
        result = []
        discovered_plugins = {
            name: importlib.import_module(name)
            for finder, name, ispkg
            in pkgutil.iter_modules()
            if name.startswith('cbpi') and len(name) > 4
        }
        for key, module in discovered_plugins.items():
            from importlib.metadata import version
            try:
                from importlib.metadata import (distribution, metadata,
                                                    version)
                meta = metadata(key)
                result.append(dict(Name=meta["Name"], Version=meta["Version"], Author=meta["Author"], Homepage=meta["Home-page"], Summary=meta["Summary"]))
                            
            except Exception as e:
                print(e)
        return tabulate(result, headers="keys")

    async def downloadlog_old(self, logtime):
        filename = "cbpi4.log"
        fullname = pathlib.Path(os.path.join(".",filename))
        pluginname = "cbpi4_plugins.txt"
        fullpluginname = pathlib.Path(os.path.join(".",pluginname))
        actorname = "cbpi4_actors.txt"
        fullactorname = pathlib.Path(os.path.join(".",actorname))
        sensorname = "cbpi4_sensors.txt"
        fullsensorname = pathlib.Path(os.path.join(".",sensorname))
        kettlename = "cbpi4_kettles.txt"
        fullkettlename = pathlib.Path(os.path.join(".",kettlename))

        output_filename="cbpi4_log.zip"

        if logtime == "b":
            os.system('journalctl -b -u craftbeerpi.service --output cat > {}'.format(fullname))
        else:
            os.system('journalctl --since \"{} hours ago\" -u craftbeerpi.service --output cat > {}'.format(logtime, fullname))

        plugins = await self.plugins_list()

        with open(fullpluginname, 'w') as f:
            f.write(plugins)

        #os.system('echo "{}" >> {}'.format(plugins,fullpluginname))

        try:
            actors = self.cbpi.actor.get_state()
            json.dump(actors['data'],open(fullactorname,'w'),indent=4, sort_keys=True)
            sensors = self.cbpi.sensor.get_state()
            json.dump(sensors['data'],open(fullsensorname,'w'),indent=4, sort_keys=True)
            kettles = self.cbpi.kettle.get_state()
            json.dump(kettles['data'],open(fullkettlename,'w'),indent=4, sort_keys=True)
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Creation of files failed: {}".format(e), NotificationType.ERROR)

        try:
            zipObj=zipfile.ZipFile(output_filename , 'w', zipfile.ZIP_DEFLATED)
            zipObj.write(fullname)
            zipObj.write(fullpluginname)
            zipObj.write(fullactorname)
            zipObj.write(fullsensorname)
            zipObj.write(fullkettlename)
            zipObj.close()
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Zip creation failed: {}".format(e), NotificationType.ERROR)

        try:
            os.remove(fullname)
            os.remove(fullpluginname)
            os.remove(fullactorname)
            os.remove(fullsensorname)
            os.remove(fullkettlename)
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Removal of original files failed: {}".format(e), NotificationType.ERROR)

    async def downloadlog(self, logtime):
        filename = "cbpi4.log"
        fullname = pathlib.Path(os.path.join(".",filename))
        pluginname = "cbpi4_plugins.txt"
        fullpluginname = pathlib.Path(os.path.join(".",pluginname))
        actorname = "cbpi4_actors.txt"
        fullactorname = pathlib.Path(os.path.join(".",actorname))
        sensorname = "cbpi4_sensors.txt"
        fullsensorname = pathlib.Path(os.path.join(".",sensorname))
        kettlename = "cbpi4_kettles.txt"
        fullkettlename = pathlib.Path(os.path.join(".",kettlename))

        output_filename="cbpi4_log.zip"

        if logtime == "b":
            if systemd_available:
                #os.system('journalctl -b -u craftbeerpi.service --output cat > {}'.format(fullname))
                j = journal.Reader()
                j.add_match(_TRANSPORT="kernel")
                result=[]
                for entry in j:
                    message=entry['MESSAGE']
                    if message.find("Booting") != -1:
                        result.append(entry['__REALTIME_TIMESTAMP'])
                j.add_match(_SYSTEMD_UNIT="craftbeerpi.service")
                j.seek_realtime(result[-1])
                for entry in j:
                    timestamp=entry['__REALTIME_TIMESTAMP']
                    message=entry['MESSAGE']
                    print(message)
                
        else:
            if systemd_available:
                result=[]
                #os.system('journalctl --since \"{} hours ago\" -u craftbeerpi.service --output cat > {}'.format(logtime, fullname))
                j = journal.Reader()
                j.add_match(_SYSTEMD_UNIT="craftbeerpi.service")
                since = datetime.now() - timedelta(hours=int(logtime))
                j.seek_realtime(since)
                for entry in j:
                    result.append(entry['MESSAGE'])
            try:
                with open(fullname, 'w') as f:
                    for line in result:
                        f.write(f"{line}\n")
            except Exception as e:
                logging.error(e)

        plugins = await self.plugins_list()
        with open(fullpluginname, 'w') as f:
            f.write(plugins)

        #os.system('echo "{}" >> {}'.format(plugins,fullpluginname))

        try:
            actors = self.cbpi.actor.get_state()
            json.dump(actors['data'],open(fullactorname,'w'),indent=4, sort_keys=True)
            sensors = self.cbpi.sensor.get_state()
            json.dump(sensors['data'],open(fullsensorname,'w'),indent=4, sort_keys=True)
            kettles = self.cbpi.kettle.get_state()
            json.dump(kettles['data'],open(fullkettlename,'w'),indent=4, sort_keys=True)
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Creation of files failed: {}".format(e), NotificationType.ERROR)

        try:
            zipObj=zipfile.ZipFile(output_filename , 'w', zipfile.ZIP_DEFLATED)
            zipObj.write(fullname)
            zipObj.write(fullpluginname)
            zipObj.write(fullactorname)
            zipObj.write(fullsensorname)
            zipObj.write(fullkettlename)
            zipObj.close()
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Zip creation failed: {}".format(e), NotificationType.ERROR)

        try:
            os.remove(fullname)
            os.remove(fullpluginname)
            os.remove(fullactorname)
            os.remove(fullsensorname)
            os.remove(fullkettlename)
        except Exception as e:
            logging.info(e)
            self.cbpi.notify("Error", "Removal of original files failed: {}".format(e), NotificationType.ERROR)


    def allowed_file(self, filename, extension):
        return '.' in filename and filename.rsplit('.', 1)[1] in set([extension])

    def recursive_chown(self, path, owner, group):
        for dirpath, dirnames, filenames in os.walk(path):
            shutil.chown(dirpath, owner, group)
            for filename in filenames:
                shutil.chown(os.path.join(dirpath, filename), owner, group)

    async def restoreConfig(self, data):
        fileData = data['File']
        filename = fileData.filename
        backup_file = fileData.file
        content_type = fileData.content_type
        required_content=['dashboard/', 'recipes/', 'upload/', 'config.json', 'config.yaml']

        if content_type == 'application/x-zip-compressed':
            try:
                content = backup_file.read()
                if backup_file and self.allowed_file(filename, 'zip'):
                    self.path = os.path.join(self.cbpi.config_folder.configFolderPath, "restored_config.zip")
                    
                    f=open(self.path, "wb")
                    f.write(content)
                    f.close()
                    zip=zipfile.ZipFile(self.path)
                    zip_content_list = zip.namelist()
                    zip_content = True
                    for content in required_content:
                        try:
                            check = zip_content_list.index(content)
                        except:
                            zip_content = False
                    if zip_content == True:
                        self.cbpi.notify("Success", "Config backup has been uploaded", NotificationType.SUCCESS)
                        self.cbpi.notify("Action Required!", "Please restart the server", NotificationType.WARNING)
                    else:
                        self.cbpi.notify("Error", "Wrong content type. Upload failed", NotificationType.ERROR)
                        os.remove(self.path)
            except:
                self.cbpi.notify("Error", "Config backup upload failed", NotificationType.ERROR)
                pass
        else:
            self.cbpi.notify("Error", "Wrong content type. Upload failed", NotificationType.ERROR)

    async def uploadSVG(self, data):
        fileData = data['File']
        filename = fileData.filename
        svg_file = fileData.file
        content_type = fileData.content_type

        logging.info(content_type)

        if content_type == 'image/svg+xml':
            try:
                content = svg_file.read().decode('utf-8','replace')
                if svg_file and self.allowed_file(filename, 'svg'):
                    self.path = os.path.join(self.cbpi.config_folder.get_file_path("dashboard"),"widgets", filename)
                    logging.info(self.path)

                    f=open(self.path, "w")
                    f.write(content)
                    f.close()
                    self.cbpi.notify("Success", "SVG file ({}) has been uploaded.".format(filename), NotificationType.SUCCESS)
            except:
                self.cbpi.notify("Error", "SVG upload failed", NotificationType.ERROR)
                pass
        else:
            self.cbpi.notify("Error", "Wrong content type. Upload failed", NotificationType.ERROR)

    async def systeminfo(self):
        logging.info("SYSTEMINFO")
        system = "" 
        temp = 0
        cpuload = 0
        cpucount = 0
        cpufreq = 0
        totalmem = 0
        availmem = 0
        mempercent = 0
        eth0IP = "N/A"
        wlan0IP = "N/A"
        eth0speed = "N/A"
        wlan0speed = "N/A"       

        TEMP_UNIT=self.cbpi.config.get("TEMP_UNIT", "C")
        FAHRENHEIT = False if TEMP_UNIT == "C" else True

        af_map = { socket.AF_INET: 'IPv4',
                   socket.AF_INET6: 'IPv6',
                   }

        try:
            if psutil.LINUX == True:
                system = "Linux"
            elif psutil.WINDOWS == True:
                system = "Windows"
            elif psutil.MACOS == True:
                system = "MacOS"
            cpuload = round(psutil.cpu_percent(interval=None),1)
            cpucount = psutil.cpu_count(logical=False)
            cpufreq = psutil.cpu_freq()
            mem = psutil.virtual_memory()
            availmem = round((int(mem.available) / (1024*1024)),1)
            mempercent = round(float(mem.percent),1)
            totalmem = round((int(mem.total) / (1024*1024)),1)
            if system == "Linux":
                try:
                    temps = psutil.sensors_temperatures(fahrenheit=FAHRENHEIT)
                    for name, entries in temps.items():
                        for entry in entries:
                            if name == "cpu_thermal":
                                temp = round(float(entry.current),1)
                except:
                    pass
            else:
                temp = "N/A"
            if system == "Linux":
                try:
                    ethernet = psutil.net_if_addrs()
                    for nic, addrs in ethernet.items():
                        if nic == "eth0":
                            for addr in addrs:
                                if str(addr.family) == "AddressFamily.AF_INET" or str(addr.family) == "2": 
                                    if addr.address:
                                        eth0IP = addr.address
                        if nic == "wlan0":
                            for addr in addrs:
                                if str(addr.family) == "AddressFamily.AF_INET" or str(addr.family) == "2": 
                                    if addr.address:
                                        wlan0IP = addr.address
                    info = psutil.net_if_stats()
                    try:
                        for nic in info:
                            if nic == 'eth0':
                                if info[nic].isup == True:
                                    if info[nic].speed:
                                        eth0speed = info[nic].speed
                                else:
                                    eth0speed = "down"
                            if nic == 'wlan0':
                                if info[nic].isup == True: 
                                    ratestring = os.popen('iwlist wlan0 rate | grep Rate').read()
                                    start = ratestring.find("=") + 1
                                    end = ratestring.find(" Mb/s")
                                    wlan0speed = ratestring[start:end]
                                else:
                                    wlan0speed = "down"
                    except Exception as e:
                        logging.info(e)
                except:
                    pass

            if system == "Windows":
                try:
                    ethernet = psutil.net_if_addrs()               
                    for nic, addrs in ethernet.items():
                        if nic == "Ethernet":
                            for addr in addrs:
                                if str(addr.family) == "AddressFamily.AF_INET": 
                                    if addr.address:
                                        eth0IP = addr.address
                        if nic == "WLAN":
                            for addr in addrs:
                                if str(addr.family) == "AddressFamily.AF_INET": 
                                    if addr.address:
                                        wlan0IP = addr.address
                    info = psutil.net_if_stats()
                    try:
                        for nic in info:
                            if nic == 'Ethernet':
                                if info[nic].isup == True:
                                    if info[nic].speed:
                                        eth0speed = info[nic].speed
                                else:
                                    eth0speed = "down"
                            if nic == 'WLAN':
                                if info[nic].isup == True:
                                    if info[nic].speed:
                                        wlan0speed = info[nic].speed
                                else:
                                    wlan0speed = "down"                    
                    except Exception as e:
                        logging.info(e)
                except:
                    pass

        except:
            pass

        systeminfo =    {'system': system,
                         'cpuload': cpuload,
                         'cpucount': cpucount,
                         'cpufreq': cpufreq.current,
                         'totalmem': totalmem,
                         'availmem': availmem,
                         'mempercent': mempercent,
                         'temp': temp,
                         'temp_unit': TEMP_UNIT,
                         'eth0': eth0IP,
                         'wlan0': wlan0IP,
                         'eth0speed': eth0speed,
                         'wlan0speed': wlan0speed}
        return systeminfo


