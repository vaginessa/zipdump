# zipdump
Analyze zipfile, either local, or from url

`zipdump` can either do a full scan, finding all PK-like headers, or it can do a quick scan ( like the usual `zip -v` type output ).

`zipdump -q`  works equally quick on web based resources as on local files.
This makes it quite easy to quickly investigate a large number of large .zip files without actually needing to download them.

I wrote this tool because i wanted to look at the contents of lots of apple ios firmware files without downloading 100s of GB of data.

For instance:

    python zipdump.py -q http://appldnld.apple.com/ios10.0/031-64655-20160705-A371AD14-3E3F-11E6-A58B-C84C60941A1E/com_apple_MobileAsset_SoftwareUpdate/d75e3af423ae0308a8b9e0847292375ba02e3b11.zip
  
`zipdump` needs pyton3.


COMMANDLINE OPTIONS
===================
 * `--cat` FILENAME    will decrypt, decompress the specified filename to stdout
 * `--raw` FILENAME    will decrypt, but not decompress the specified filename to stdout
 * `--save` FILENAME   will save the decrypted, decompressed file to the output directory
 * `--outputdir` DIR   specify where to save extracted files.
 * `--quick`           will quickly scan a file, without investigating the entire file.
 * `--offset OFS --length SIZE`   specify a chunk of a file to investigate
    you can used this to list zip contents from a zip file embeded in another binary file.
 * `--dumpraw`         hexdump the entire zip file contents.
 * `--keys  0x1,0x2,0x3`  specify the internal encryption key for decrypting encrypted files.
 * `--password  PASSWD `  specify the password for decrypting encrypted files.
 * `--hexpassword  HEXPASSWD `  specify the password for decrypting encrypted files.
    useful when the password is not an ascii string.

(c) 2016 Willem Hengeveld <itsme@xs4all.nl>
