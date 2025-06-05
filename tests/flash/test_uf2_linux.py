# import pytest
# from unittest import mock
# from mpflash.flash.uf2.uf2disk import UF2Disk
# from mpflash.flash.uf2.linux import get_uf2_drives

# @pytest.fixture
# def mock_blkinfo():
#     with mock.patch("mpflash.flash.uf2.linux.BlkDiskInfo") as mock_blkinfo_cls:
#         yield mock_blkinfo_cls

# def test_get_uf2_drives_no_disks(mock_blkinfo):
#     mock_blkinfo.return_value.get_disks.return_value = []
#     drives = list(get_uf2_drives())
#     assert drives == []

# def test_get_uf2_drives_vfat_direct(mock_blkinfo):
#     mock_blkinfo.return_value.get_disks.return_value = [
#         {
#             "name": "sdb",
#             "fstype": "vfat",
#             "label": "UF2BOOT",
#             "mountpoint": "/media/UF2BOOT",
#             "type": "disk",
#         }
#     ]
#     drives = list(get_uf2_drives())
#     assert len(drives) == 1
#     assert drives[0].device_path == "/dev/sdb"
#     assert drives[0].label == "UF2BOOT"
#     assert drives[0].mountpoint == "/media/UF2BOOT"

# def test_get_uf2_drives_vfat_child_partition(mock_blkinfo):
#     mock_blkinfo.return_value.get_disks.return_value = [
#         {
#             "name": "sdc",
#             "type": "disk",
#             "children": [
#                 {
#                     "name": "sdc1",
#                     "fstype": "vfat",
#                     "label": "UF2BOOT",
#                     "mountpoint": "/media/UF2BOOT",
#                     "type": "part",
#                 }
#             ],
#         }
#     ]
#     drives = list(get_uf2_drives())
#     assert len(drives) == 1
#     assert drives[0].device_path == "/dev/sdc1"
#     assert drives[0].label == "UF2BOOT"
#     assert drives[0].mountpoint == "/media/UF2BOOT"

# def test_get_uf2_drives_no_vfat(mock_blkinfo):
#     mock_blkinfo.return_value.get_disks.return_value = [
#         {
#             "name": "sdd",
#             "fstype": "ext4",
#             "label": "NOT_UF2",
#             "mountpoint": "/media/NOT_UF2",
#             "type": "disk",
#         }
#     ]
#     drives = list(get_uf2_drives())
#     assert drives == []
