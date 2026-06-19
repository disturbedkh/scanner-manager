Model: UNIDEN SDS100

Downgrade from 1.23.15 Main to 1.23.07 Main.  

Caution: Do not put different firmware versions on the SD card at the same time. If there are different versions, the upload will not start or will not be uploaded correctly, so please be sure to upload only one version. 　

If you accidentally delete two dat files already included in the SD card that are not related to Firmware, SDS100 will not start properly. If you accidentally delete these files, you can restore them by executing "Clear User Data..." via Sentinel, but all User Data will be lost.


Please back up contents in SD card and your settings via Sentinel just in case.
Please make sure the battery is fully charged before starting.

Steps:
Turn On the SDS100
Connect the Windows PC and SDS100 with a USB cable. 

SDS100 Screen:
++++++++++++++++++++
USB Cable Detected
Select USB mode

Mass Storage = "E"
Serial Port ="."
++++++++++++++++++++

Press "E(Yes)" key to select "Mass Storage" 

SDS100 Screen:
++++++++++++++++++++
USB Mass Storage
++++++++++++++++++++

Open Windows Explorer. 
A folder for Removable disk "BCDx36HP" will appear.
Open the "firmware" folder inside "BCDx36HP" folder.

There are two "dat" files inside.　Do not touch these files.

> Downgrade from V1.23.15 Main.
Copy and paste "SDS-100_V1_23_07.bin" files to this folder.

Windows Explorer Screen:
+++++++++++++++++++

Removable disk (X:)  X = varies depending of PC settings. 
 
BCDx36HP
 L activity_log
   .
   .
   firmware <--- Open this folder.
    L CitiTable_V00_00.dat <-- Do not touch.  
      ZipTable_V00_00.dat <-- Do not touch.
      SDS-100_V1_23_07.bin <-- Copy main (.bin) firmware to here*.

++++++++++++++++++++
* Do not upload multiple main firmware. 

After the copy is complete, reset the power, update will start automatically. 
!! Do not turn off the power until the upload is complete !!

Note: After the process is finished, these firmware files will be automatically deleted from the "firmware" folder.


Caution: Please use these files on your risk. Uniden is not responsible for any damage caused by these processes.
