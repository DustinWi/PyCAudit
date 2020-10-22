# PyCAudit

## Introduction
Python Configuration Audit, PyCAudit, is intended to allow the user to read in a text based template that utilizes 
regular expressions to match against network device configurations.  While this is the intent, technically it 
could be used for any text based template audit scenario.

## Dependencies
* Python3 (Tested with Python 3.8.0)
* re

## Syntax
This is an example template that can be used to audit configuration files.

### Special syntax:
<pre>
  # - Any line beginning with # is a comment, and will be removed from the template at runtime before
       configurations are compared against this template

  ++ - Lines beginning with ++ indicate a section.  The text following ++ is only significant to the person
       creating the template, and is not used in the script logic.

  Whitespace - If a line begins with white space (tab, space, etc.), this indicates
       that the current line is a configuration under the previous line that does not start with whitespace

  :: - Lines beginning with :: indicate criteria that must be met to include this part of the template.
       Criteria lines only apply to the section they are included in.  If this is included before the first
       section, the criterial is reviewed before any sections are processed.  See "Criteria Property" below.
       Syntax:
         ::property::regular_expression
  !! - Lines beginning with !! are the same as ::, except they are exempt instead of included for review.

  && - Lines that begin with && are the same as ::, except they apply to each block within a section.
       This is very useful for things like using the same criteria for multiple interface blocks.
       If this is placed within a template block, it will be ignored.

  || - Lines that begin with || are the same as &&, except it exempts the blocks instead of includes them.

  == - *** FUTURE *** Lines beginning with == indicate that block of the template must match all lines indicated,
       in the order it is indicated, and nothing extra.  This only applies to portions of the template that
       include sub-commands, like access-lists and interfaces

  -- - Lines beginning with -- indicate that the line should not appear in the configuration.
</pre>

### Criteria Properties:
Script Specific Properties:
<pre>
  Value            Property                              Description
  =====            ========                              ===========
  config           Section Configuration                 Compare the regular expression against the current section of the configuration
                                                           If this criteria is placed outside of a sub-command block, the criteria is
                                                           used to match against all sub-command blocks in that section.
  global           Global Configuration                  Compare the regular expression against the global configuration of the device
</pre>
  
## Template Examples
<pre>
# Only audit switches from building 4
::config::hostname sw_building4_.*

++GlobalConfig
# Make sure NTP servers are set correctly
ntp server 1.1.1.1 prefer
ntp server 1.1.1.2

# Make sure the hostname matches the approved naming standard
hostname sw_building4_[0-9]{3}_\S{1,7}$

# Make sure the correct syslog server is set
logging host 1.1.1.1

++InterfaceRequirements
# Do not audit uplink ports or ports that are shutdown
||config||description .*uplink.*
||config||shutdown

# All interfaces must have these settings
interface .*
  # Must have a description
  description .*
  # Must have a switchport mode set
  switchport mode (trunk|access)
  # Must be using an access vlan that is not vlan 1
  switchport access vlan [^1]$

# Trunk interfaces must have these settings
interface .*
 # Only audit trunk interfaces
 ::config::switchport mode trunk
 # Must have a VLAN list applied
 switchport trunk allowed vlan .*
 # Must have a native vlan specified that is not 1
 switchport trunk native vlan [^1].*
 
# Access Interfaces
interface .*
 # Only audit access ports in this block
 ::config::switchport mode access
 # Must have root guard enabled
 spanning-tree guard root enabled
 # Must enable portfase
 spanning-tree portfast enable
</pre>
 
## Sample results
Results are saved as a list of dictionaries, resembling JSON formatting.
<pre>
[
  {
    "type": "missing",
    "section": "GlobalConfig",
    "Template_Value": "ntp server 1.1.1.1 prefer",
    "Config_Value": ""
  },
  {
    "type": "missing",
    "section": "GlobalConfig",
    "Template_Value": "ntp server 1.1.1.2",
    "Config_Value": ""
  },
  {
    "type": "missing",
    "section": "GlobalConfig",
    "Template_Value": "hostname sw_building4_[0-9]{3}_\\S{1,7}$",
    "Config_Value": ""
  },
  {
    "type": "missing",
    "section": "GlobalConfig",
    "Template_Value": "logging host 1.1.1.1",
    "Config_Value": ""
  },
  {
    "type": "missing",
    "section": "InterfaceRequirements",
    "Template_Value": "interface gigabitethernet 1/0/1\n switchport access vlan [^1]$",
    "Config_Value": "interface gigabitethernet 1/0/1\n description a test interface\n switchport mode access"
  },
  {
    "type": "missing",
    "section": "InterfaceRequirements",
    "Template_Value": "interface gigabitethernet 1/0/1\n spanning-tree guard root enabled",
    "Config_Value": "interface gigabitethernet 1/0/1\n description a test interface\n switchport mode access"
  }
]</pre>