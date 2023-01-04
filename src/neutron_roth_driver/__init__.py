#!/usr/bin/env python
# Copyright 2022 Datto, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import site
import glob
import configparser

print("Locating neutron entry_points...")

_ENTRY_POINTS = glob.glob(
    site.getsitepackages()[0] +
    "/neutron-*dist-info/entry_points.txt",
    recursive=True
)[0]


def main():
    try:
        print("Parsing neutron entry_points...")
        config = configparser.ConfigParser()
        config.read(_ENTRY_POINTS)

        print("Add roth entry_point under neutron.ml2.mechanism_drivers...")
        config.set(
            'neutron.ml2.mechanism_drivers',
            'roth',
            'neutron_roth_driver.roth_driver:RotHMechanismDriver'
        )

        print("Saving changes to %s..." % _ENTRY_POINTS)
        file = open(_ENTRY_POINTS, 'w')
        config.write(file)
        file.close()

        print("Install completed!")
        print("Note: Please restart neutron-server to enable roth driver.")
    except Exception as E:
        print("ERROR: neutron-roth-driver failed to install.")
        print(E)
