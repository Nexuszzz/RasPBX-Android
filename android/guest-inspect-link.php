<?php
include '/etc/freepbx.conf';
$p=FreePBX::create();
echo "ANDROID DEVICES\n";
foreach($p->Core->getAllDevicesByType() as $item){echo $item['id'],": ",$item['description'],"\n";}
echo "TRUNKS\n";
foreach($p->Core->listTrunks() as $id=>$item){echo $id,": ",$item['name'],"\n";}
