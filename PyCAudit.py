import json
import re


class PyCAudit:
    def __init__(self, config, template):
        self.template_original = template
        self.config = config
        self.template_string = None
        self.result = []
        self.template = self.parse_template()

    def parse_template(self):
        # Initialize template dictionary
        template = {
            "device_positive_criteria": {},
            "device_negative_criteria": {},
            "sections": {}
        }

        # Remove Comments from template
        self.template_string = re.sub(r'(?m)^[ \t]*#.*\n?', '', self.template_original)

        # Cleanup any \r\n funny business
        self.template_string = self.template_string.replace("\r\n", "\n")

        # Add logic to find criteria prior to the first section
        for line in self.template_string.split("\n"):
            # Skip Blank Lines
            if re.compile(r'^$').search(line):
                continue
            # If we hit a section marker stop looking
            if line.startswith("++"):
                break
            # Add any positive criteria to the list
            if line.startswith("::"):
                key, value = line.split("::")[1:]
                template["device_positive_criteria"][key] = value
            # Add any negative criteria to the list
            if line.startswith("!!"):
                key, value = line.split("!!")[1:]
                template["device_negative_criteria"][key] = value

        # Find all sections in the template file, and assign them to the template variable
        sections = re.compile(r'^\+\+(.*)\n((?:[^+]{2}.*\n)*)', re.MULTILINE).findall(self.template_string)
        for section in sections:
            key = section[0]
            value = section[1]
            template["sections"][key] = {}
            # Each section should have positive and negative criteria elements
            template["sections"][key]["section_positive_criteria"] = []
            template["sections"][key]["section_negative_criteria"] = []
            template["sections"][key]["section_positive_repeat_criteria"] = []
            template["sections"][key]["section_negative_repeat_criteria"] = []
            # Parse the section to move criteria to proper variable
            for line in value.split("\n"):
                criteria_property = None
                pattern = None
                # Positive criteria goes to the positive dictionary
                if line.startswith("::"):
                    criteria_property, pattern = line.split("::")[1:]
                    template["sections"][key]["section_positive_criteria"].append(
                    {"property": criteria_property, "pattern": pattern})
                # Negative criteria goes to the negative dictionary
                if line.startswith("!!"):
                    criteria_property, pattern = line.split("!!")[1:]
                    template["sections"][key]["section_negative_criteria"].append(
                    {"property": criteria_property, "pattern": pattern})
                # Positive repeat criteria goes to the positive repeat dictionary
                if line.startswith("&&"):
                    criteria_property, pattern = line.split("&&")[1:]
                    template["sections"][key]["section_positive_repeat_criteria"].append(
                    {"property": criteria_property, "pattern": pattern})
                # Negative repeat criteria goes to the negative repeat dictionary
                if line.startswith("||"):
                    criteria_property, pattern = line.split("||")[1:]
                    template["sections"][key]["section_negative_repeat_criteria"].append(
                    {"property": criteria_property, "pattern": pattern})
                # If we found a criteria, remove it from the value
                if criteria_property:
                    value = value.replace("{}\n".format(line), "")

            # Parse the actual rules and create blocks of commands
            # template["sections"][key]["blocks"] will contain a list of rule dictionaries
            template["sections"][key]["blocks"] = []
            current_block = None
            for line in value.split("\n"):
                # Build the current rule and append it to the blocks list
                # If the current line is blank, skip it
                if line.strip() == '':
                    continue
                # If line starts with non-whitespace, create a new rule
                if re.compile(r'^\S').search(line):
                    # If there is already a current_block, append it to the template variable before
                    #   creating a new block of commands
                    if current_block:
                        template["sections"][key]["blocks"].append(current_block)
                    current_block = {}
                    # Each rule is either a positive or negative match
                    #   Positive: True - Must be in the config
                    #   Negative: False - Must not appear in config
                    if line.startswith("--"):
                        line = line[2:]
                        rule_type = False
                    else:
                        rule_type = True
                    current_block["rule"] = (line, rule_type)
                    current_block["block_positive_criteria"] = []
                    current_block["block_negative_criteria"] = []
                    current_block["sub-rules"] = []
                # Put criteria where it belongs
                block_property = None
                block_pattern = None
                # Move positive criteria to the block criteria
                if re.compile(r'^\s*::').search(line):
                    block_property, block_pattern = line.split("::")[1:]
                    current_block["block_positive_criteria"].append(
                        {"property": block_property, "pattern": block_pattern})
                # Move negative criteria to the block criteria
                if re.compile(r'^\s*!!').search(line):
                    block_property, block_pattern = line.split("!!")[1:]
                    current_block["block_negative_criteria"].append(
                        {"property": block_property, "pattern": block_pattern})
                # If the line is criteria, move to the next line
                if block_property:
                    continue
                # If the line begins with whitespace that is not a new line, add it to the current block
                if re.compile(r'^(?!\n)\s').search(line):
                    if line.strip().startswith("--"):
                        line = line.strip()[2:]
                        child_rule_type = False
                    else:
                        child_rule_type = True
                    current_block["sub-rules"].append((line.strip(), child_rule_type))

            # Finished processing the blocks, need to add the final built block to the list of blocks
            template["sections"][key]["blocks"].append(current_block)

        return template

    def audit(self):
        # Set Debugging to True or False
        debug = False
        self.result = []

        ################################### BEGIN Harvesting Running Configuration #######################################
        # Get the device name, full config, software version, and decide which req_block_X to use
        # You'll need to read your config file into "device_config"
        device_config = self.config

        # Couldn't get live or baseline config, log error and move on
        if (not device_config) or (device_config is None) or (device_config == ''):
            self.result.append({
                'type': 'error',
                'section': '',
                'Template_Value': '',
                'Config_Value': 'Could not read configuration file'
            })
            return

        # Let's normalize the newlines in the config so we only have to deal with one type, \n.
        # Also, convert the config to lowercase for uniformity
        device_config = device_config.lower().replace('\r\n', '\n').replace('\r', '\n')
        # Someone thought it would be a good idea to let some of the lines in the Cisco configurations end
        #  in whitespace.  Let's try to remove those.
        device_config = re.sub(r'\s+\n', '\n', device_config)
        ################################### END Harvesting Running Configuration #######################################

        ################################### BEGIN Validating Device Properties #########################################
        template = self.template

        # Skip any devices that don't match device criteria
        #  Create a list of custom properties.  This will help us know if we are doing our
        #   own logic based on the property provided in the template, or looking at something
        #   that Netbrain gathers
        custom_properties = [
            'config'
        ]

        # Make sure the device matches the possitive global criteria
        for criteria, pattern in template["device_positive_criteria"].items():
            # Add logic for 'config' property here
            if criteria == "config":
                # Search the config for the given value
                if not re.compile(pattern, re.MULTILINE).search(device_config):
                    self.result.append({
                        'type': 'unsupported',
                        'section': '',
                        'Template_Value': "{}: {}".format(criteria, pattern),
                        'Config_Value': device_config})
                    return

        # Make sure the device does not match the negative global criteria
        for criteria,pattern in template["device_negative_criteria"].items():
            # Add logic for 'config' property here
            if criteria == "config":
                if re.compile(pattern, re.MULTILINE).search(device_config):
                    self.result.append({
                        'type': 'unsupported',
                        'section': '',
                        'Template_Value': "{}: {}".format(criteria, pattern),
                        'Config_Value': device_config})
                    return

        ################################### END Validating Device Properties #########################################

        ################################### BEGIN Validating Sections From Template ##################################
        for section, content in template["sections"].items():
            # If the device doesn't meet this sections criteria, skip it
            failed = False
            # Check for positive criteria
            for section_property in content["section_positive_criteria"]:
                temp_property = section_property['property']
                temp_pattern = section_property['pattern']
                if temp_property == "config":
                    if not re.compile(temp_pattern, re.MULTILINE).search(device_config):
                        failed = True

            # If failed is True, this section is not for this device.  Continue to the next section
            if failed is True:
                continue

            # Check for Negative criteria
            for section_property in content["section_negative_criteria"]:
                temp_property = section_property['property']
                temp_pattern = section_property['pattern']
                if temp_property == "config":
                    print("Checking config for {}".format(temp_pattern))
                    if re.compile(temp_pattern, re.MULTILINE).search(device_config):
                        print("Negative criteria matched, deviced failed criteria validation.")
                        failed = True

            # If failed is True, this section is not for this device.  Continue to the next section
            if failed is True:
                continue

            # If we made it here, this section does apply to this device.  Let's audit the device
            for block in content["blocks"]:
                rule = block["rule"][0]
                rule_type = block["rule"][1]
                sub_rules = block["sub-rules"]
                # Grab the lists of block criteria
                block_positive_criteria = block["block_positive_criteria"]
                block_negative_criteria = block["block_negative_criteria"]
                # If there is no matching config_block, that's a finding.  Log it to the table and move on
                config_blocks = re.compile('^((?:{}$)(?:(?:\n .*))*)'.format(rule), re.MULTILINE).findall(device_config)
                # Decide what to do depending on if the rule is a positive or negative rule
                if rule_type == True:
                    if len(config_blocks) == 0:
                        self.result.append({
                            'type': 'missing',
                            'section': section,
                            'Template_Value': rule,
                            'Config_Value': ''
                        })
                        continue
                else:
                    if len(config_blocks) > 0:
                        for entry in config_blocks:
                            self.result.append({
                                'type': 'extra',
                                'section': section,
                                'Template_Value': rule,
                                'Config_Value': entry
                            })
                            continue

                for config_block in config_blocks:
                    # Validate block criteria
                    # Extract the matched rule from the current config_block
                    ## If the rule contains capturing groupings, the lookup below will contain a tuple instead of a string.
                    if debug is True:
                        print("Rule:\n{}\nConfig Block:\n{}".format(rule,config_block))
                    if isinstance(config_block, tuple):
                        config_block = config_block[0]
                    try:
                        rule_match = re.compile('.*{}.*'.format(rule), re.MULTILINE).findall(config_block)[0]
                    except:
                        print("Lookup of rule in config block failed.\nRule:\n{}\nConfig Block:\n{}".format(
                            rule,
                            config_block
                            ))
                        continue

                    # Validate against section repeat criteria first
                    failed = False
                    for section_property in content["section_positive_repeat_criteria"]:
                        temp_property = section_property['property']
                        temp_pattern = section_property['pattern']
                        if temp_property == "config":
                            if not re.compile(temp_pattern, re.MULTILINE).search(config_block):
                                failed = True
                    for section_property in content["section_negative_repeat_criteria"]:
                        temp_property = section_property['property']
                        temp_pattern = section_property['pattern']
                        if temp_property == "config":
                            if re.compile(temp_pattern, re.MULTILINE).search(config_block):
                                failed = True
                    # Now validate the block criteria
                    for section_property in block["block_positive_criteria"]:
                        temp_property = section_property['property']
                        temp_pattern = section_property['pattern']
                        if temp_property == "config":
                            if not re.compile(temp_pattern, re.MULTILINE).search(config_block):
                               failed = True
                    for section_property in block["block_negative_criteria"]:
                        temp_property = section_property['property']
                        temp_pattern = section_property['pattern']
                        if temp_property == "config":
                            if re.compile(temp_pattern, re.MULTILINE).search(config_block):
                                failed = True

                    # If failed is True the configuration block does not meet the criteria, skip the block
                    if failed is True:
                        continue

                    # Finally, it is time to audit the interface against this section's template
                    ## Use block_fail to know if we need to insert the block rule (top level command) into the error
                    ##   variable or not when a missing sub-rule is found
                    block_failed = False
                    error = ''
                    error_brief = ''
                    infractions = []
                    for sub_rule in sub_rules:
                        sub_rule_orig = sub_rule
                        sub_rule = sub_rule_orig[0].strip()
                        sub_rule_type = sub_rule_orig[1]
                        match = False
                        infraction = []
                        for line in config_block.split('\n'):
                            line = line.strip()
                            if re.compile('^{}'.format(sub_rule), re.MULTILINE).search(line):
                                match = True
                                break

                        if not match == sub_rule_type:
                            # Determine if this is a rule or a sub-rule mismatch
                            if block_failed == False:
                                error += '\n{}'.format(rule_match)
                                block_failed = True
                            error += '\n {}'.format(sub_rule)
                            if sub_rule_type:
                                if not 'missing' in infractions:
                                    infractions.append('missing')
                            else:
                                if not 'extra' in infractions:
                                    infractions.append('extra')

                    if block_failed == True:
                        error = error.strip()
                        # Strip the first line of the block for the brief value if it is an interface block
                        self.result.append({
                            'type': ','.join(infractions),
                            'section': section,
                            'Template_Value': error,
                            'Config_Value' : config_block
                        })
        ################################### END Validating Sections From Template ##################################

        ############################ Final Validation Cleanup ###################################
        # If no infringements found, add row to show that the device complies
        if len(self.result) == 0:
            self.result.append({
                'type': 'comply',
                'section': '',
                'Template_Value': '',
                'Config_Value' : ''
            })
#

if __name__ == '__main__':
    my_template = '''# Only audit switches from building 4
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
 spanning-tree portfast enable'''

    my_config = '''hostname sw_building4_core
...
some more config lines
...
interface GigabitEthernet 1/0/1
 description A Test Interface
 switchport mode access
!
'''
    my_audit = PyCAudit(my_config, my_template)
    my_audit.audit()
    print(json.dumps(my_audit.result, indent=2))
    print(json.dumps(my_audit.template, indent=2))
