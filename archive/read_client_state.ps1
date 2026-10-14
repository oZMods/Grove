param([int]$ClientProcessId = 0)
$ErrorActionPreference = 'Stop'
if ($ClientProcessId -eq 0) {
 $clientCandidates = @(Get-Process -Name osclient -ErrorAction Stop)
 if ($clientCandidates.Count -ne 1) { throw 'Specify -ClientProcessId when multiple clients are running.' }
 $ClientProcessId = $clientCandidates[0].Id
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ClientMemoryReader {
 [StructLayout(LayoutKind.Sequential)] public struct Point { public int X; public int Y; }
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left; public int Top; public int Right; public int Bottom; }
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr window, out Rect rect);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out Rect rect);
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr window, ref Point point);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out Point point);
 [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr window, ref Point point);
 [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
 [DllImport("kernel32.dll", SetLastError=true)] public static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] buffer, UIntPtr size, out UIntPtr read);
 [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
'@
$clientProcess = Get-Process -Id $ClientProcessId
if ($clientProcess.ProcessName -ne 'osclient') { throw 'Unexpected process' }
$expectedBinaryHash = '3852DD48AA6A75CFB042489B5192B477A1B828CBC95AF8B759C139095C8B6EA2'
$installedBinaryHash = (Get-FileHash -LiteralPath $clientProcess.MainModule.FileName -Algorithm SHA256).Hash
if ($installedBinaryHash -ne $expectedBinaryHash) { throw 'Installed client does not match the IDA input build. Do not use these offsets.' }
$clientBase = $clientProcess.MainModule.BaseAddress.ToInt64()
$clientHandle = [ClientMemoryReader]::OpenProcess(0x410, $false, $ClientProcessId)
if ($clientHandle -eq [IntPtr]::Zero) { throw "OpenProcess failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }
function Read-ClientBytes([long]$Address, [int]$Count) {
 $buffer = [byte[]]::new($Count)
 $readCount = [UIntPtr]::Zero
 if (-not [ClientMemoryReader]::ReadProcessMemory($clientHandle, [IntPtr]$Address, $buffer, [UIntPtr]::new([ulong]$Count), [ref]$readCount) -or $readCount.ToUInt64() -ne $Count) { throw ('Read failed at 0x{0:X}: {1}' -f $Address, [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
 return ,$buffer
}
function Read-ClientQword([long]$Address) { [BitConverter]::ToInt64((Read-ClientBytes $Address 8), 0) }
function Read-ClientDword([long]$Address) { [BitConverter]::ToInt32((Read-ClientBytes $Address 4), 0) }
function Read-ClientString([long]$Address) {
 $stringData=Read-ClientBytes $Address 24
 if ($stringData[23] -ge 128) {
  $stringSize=[BitConverter]::ToInt64($stringData,8)
  if ($stringSize -lt 0 -or $stringSize -gt 512) { return '<invalid string>' }
  if ($stringSize -eq 0) { return '' }
  $stringData=Read-ClientBytes ([BitConverter]::ToInt64($stringData,0)) $stringSize
 }
 $terminator=[Array]::IndexOf($stringData,[byte]0)
 if ($terminator -lt 0) {$terminator=$stringData.Length}
 return [Text.Encoding]::UTF8.GetString($stringData,0,$terminator)
}
function Read-LocDefinition([int]$TypeId) {
 if ($locDefinitionCache.ContainsKey($TypeId)) {return $locDefinitionCache[$TypeId]}
 $definitionNode=Read-ClientQword ($definitionBuckets+8*($TypeId%$definitionBucketCount))
 for($definitionChain=0;$definitionNode -ne 0 -and $definitionNode -ne $definitionSentinel -and $definitionChain -lt 256;$definitionChain++) {
  if((Read-ClientQword $definitionNode) -eq $TypeId) {
   $definitionPointer=Read-ClientQword ($definitionNode+16)
   if($definitionPointer -eq 0) {break}
   $operationStart=Read-ClientQword ($definitionPointer+232)
   $operationEnd=Read-ClientQword ($definitionPointer+240)
   $operationCount=[int](($operationEnd-$operationStart)/64)
   $operations=@(if($operationCount -ge 0 -and $operationCount -le 20) {for($opIndex=0;$opIndex -lt $operationCount;$opIndex++){Read-ClientString ($operationStart+64*$opIndex)}})
   $definition=[pscustomobject]@{Name=(Read-ClientString ($definitionPointer+64));Ops=$operations}
   $locDefinitionCache[$TypeId]=$definition
   return $definition
  }
  $definitionNode=Read-ClientQword ($definitionNode+64)
 }
 return [pscustomobject]@{Name='<uncached>';Ops=@()}
}
function Project-ScenePoint([long]$ScenePointer,[int]$FineX,[int]$FineY,[int]$FineZ) {
 $cameraValues=Read-ClientBytes ($ScenePointer+1048) 16
 $sinPitch=[BitConverter]::ToSingle($cameraValues,0)
 $cosPitch=[BitConverter]::ToSingle($cameraValues,4)
 $sinYaw=[BitConverter]::ToSingle($cameraValues,8)
 $cosYaw=[BitConverter]::ToSingle($cameraValues,12)
 $relativeX=[single]($FineX-$renderInfo.CameraX)
 $relativeY=[single]($FineY-$renderInfo.CameraY)
 $relativeZ=[single]($FineZ-$renderInfo.CameraZ)
 $yawDepth=[single]([single]($cosYaw*$relativeZ)-[single]($sinYaw*$relativeX))
 $horizontal=[single]([single]($cosYaw*$relativeX)+[single]($sinYaw*$relativeZ))
 $vertical=[single]([single]($cosPitch*$relativeY)-[single]($sinPitch*$yawDepth))
 $depth=[single]([single]($sinPitch*$relativeY)+[single]($cosPitch*$yawDepth))
 if($depth -le 50) {return $null}
 $viewportPointer=Read-ClientQword ($viewportContext+8)
 $viewportData=Read-ClientBytes $viewportPointer 92
 $zoom=[BitConverter]::ToInt32($viewportData,16)
 $projectedX=[BitConverter]::ToInt32($viewportData,20)+[BitConverter]::ToInt32($viewportData,88)+[Math]::Truncate([single]([single]($zoom*$horizontal)/$depth))
 $projectedY=[BitConverter]::ToInt32($viewportData,24)+[BitConverter]::ToInt32($viewportData,80)+[Math]::Truncate([single]([single]($zoom*$vertical)/$depth))
 if($renderInfo.LogicalWidth -le 0 -or $renderInfo.LogicalHeight -le 0) {return $null}
 $pixelX=[Math]::Round([single]([single]($renderInfo.PhysicalWidth/$renderInfo.LogicalWidth)*$projectedX),[MidpointRounding]::AwayFromZero)
 $pixelY=[Math]::Round([single]([single]($renderInfo.PhysicalHeight/$renderInfo.LogicalHeight)*$projectedY),[MidpointRounding]::AwayFromZero)
 return [pscustomobject]@{X=[int]$pixelX;Y=[int]$pixelY;InClient=$pixelX -ge 0 -and $pixelY -ge 0 -and $pixelX -lt $renderInfo.PhysicalWidth -and $pixelY -lt $renderInfo.PhysicalHeight;Validation='Candidate: hover/menu confirmation required';CoordinateSpace='client area pixels'}
}
try {
 $clientState = Read-ClientQword ($clientBase + 0xE98C18)
 $rendererBase=Read-ClientQword ($clientState+144)
 $viewportContext=$rendererBase+432
 $viewportVtable=Read-ClientQword $viewportContext
 $viewportGetter=Read-ClientQword ($viewportVtable+8)
 $renderInfo=[pscustomobject]@{RendererPointer=('0x{0:X}' -f $rendererBase);ViewportGetterRva=('0x{0:X}' -f ($viewportGetter-$clientBase));CameraX=(Read-ClientDword ($clientState+0x895D8));CameraY=(Read-ClientDword ($clientState+0x895DC));CameraZ=(Read-ClientDword ($clientState+0x895E0));LogicalWidth=(Read-ClientDword ($rendererBase+48));LogicalHeight=(Read-ClientDword ($rendererBase+52));PhysicalWidth=(Read-ClientDword ($rendererBase+108));PhysicalHeight=(Read-ClientDword ($rendererBase+112))}
 $effective = Read-ClientBytes ($clientState + 13152) 100
 $levels = Read-ClientBytes ($clientState + 13252) 100
 $xp = Read-ClientBytes ($clientState + 13352) 100
 $stats = for ($statIndex=0; $statIndex -lt 25; $statIndex++) { [pscustomobject]@{Index=$statIndex;Effective=[BitConverter]::ToInt32($effective,$statIndex*4);Base=[BitConverter]::ToInt32($levels,$statIndex*4);XP=[BitConverter]::ToInt32($xp,$statIndex*4)} }
 $inventoryBuckets = Read-ClientQword ($clientBase + 0x154FAB8)
 $inventoryBucketCount = Read-ClientDword ($clientBase + 0x154FAC0)
 if ($inventoryBucketCount -lt 1 -or $inventoryBucketCount -gt 65536) { throw 'Invalid inventory bucket count' }
 $inventorySentinel = Read-ClientQword ($inventoryBuckets + 8*$inventoryBucketCount)
 $seenContainers = [Collections.Generic.HashSet[long]]::new()
 $containers = @(for ($bucketIndex=0; $bucketIndex -lt $inventoryBucketCount; $bucketIndex++) {
  $containerNode = Read-ClientQword ($inventoryBuckets + 8*$bucketIndex)
  for ($chainIndex=0; $containerNode -ne 0 -and $containerNode -ne $inventorySentinel -and $chainIndex -lt 256; $chainIndex++) {
   if (-not $seenContainers.Add($containerNode)) { break }
   $containerData = Read-ClientBytes $containerNode 64
   $containerId = [BitConverter]::ToInt32($containerData,0)
   $itemStart = [BitConverter]::ToInt64($containerData,8)
   $itemEnd = [BitConverter]::ToInt64($containerData,16)
   $quantityStart = [BitConverter]::ToInt64($containerData,32)
   $quantityEnd = [BitConverter]::ToInt64($containerData,40)
   $slotCount = [int](($itemEnd-$itemStart)/4)
   if ($slotCount -ge 0 -and $slotCount -le 2048 -and $quantityEnd-$quantityStart -eq 4*$slotCount) {
    $slots = @(if ($slotCount -gt 0) {
     $items = Read-ClientBytes $itemStart (4*$slotCount)
     $quantities = Read-ClientBytes $quantityStart (4*$slotCount)
     for ($slotIndex=0; $slotIndex -lt $slotCount; $slotIndex++) { $itemId=[BitConverter]::ToInt32($items,4*$slotIndex); if ($itemId -ge 0) { [pscustomobject]@{Slot=$slotIndex;ItemId=$itemId;Quantity=[BitConverter]::ToInt32($quantities,4*$slotIndex)} } }
    })
    [pscustomobject]@{ContainerId=$containerId;SlotCount=$slotCount;Items=$slots}
   }
   $containerNode = [BitConverter]::ToInt64($containerData,56)
  }
 })
 $localIndex = Read-ClientDword ($clientState + 52316)
 $definitionBuckets=Read-ClientQword ($clientBase+0xD22A30)
 $definitionBucketCount=Read-ClientDword ($clientBase+0xD22A38)
 if($definitionBucketCount -lt 1 -or $definitionBucketCount -gt 65536) {throw 'Invalid definition cache size'}
 $definitionSentinel=Read-ClientQword ($definitionBuckets+8*$definitionBucketCount)
 $locDefinitionCache=@{}
 $nearbyObjects=[Collections.Generic.List[object]]::new()
 $interfaceManager=Read-ClientQword ($clientState+4275176)
 $interfaceGroupCount=Read-ClientQword ($interfaceManager+26760)
 $interfaceGroups=Read-ClientQword ($interfaceManager+26768)
 $bankComponents=@()
 $bankInventorySlots=[Collections.Generic.List[object]]::new()
 $bankGroupCoordinates=@()
 $coordinateBuckets=Read-ClientQword ($clientState+4275408)
 $coordinateBucketCount=Read-ClientDword ($clientState+4275416)
 if($coordinateBucketCount -ge 1 -and $coordinateBucketCount -le 65536) {
  $coordinateSentinel=Read-ClientQword ($coordinateBuckets+8*$coordinateBucketCount)
  $bankGroupCoordinates=@(foreach($coordinateGroup in @(12,15)) {
   $coordinateNode=Read-ClientQword ($coordinateBuckets+8*($coordinateGroup%$coordinateBucketCount))
   for($coordinateChain=0;$coordinateNode -ne 0 -and $coordinateNode -ne $coordinateSentinel -and $coordinateChain -lt 256;$coordinateChain++) {
    if((Read-ClientDword $coordinateNode) -eq $coordinateGroup) {
     $coordinateBytes=Read-ClientBytes ($coordinateNode+4) 32
     [pscustomobject]@{Group=$coordinateGroup;RawDwords=@(for($coordinateField=0;$coordinateField -lt 8;$coordinateField++){[BitConverter]::ToInt32($coordinateBytes,4*$coordinateField)});Validation='Native interface coordinates; field semantics pending'}
     break
    }
    $coordinateNode=Read-ClientQword ($coordinateNode+40)
   }
  })
 }
 $currentRenderCycle=Read-ClientDword ($clientState+4273164)
 foreach($groupId in @(12,15)) {
 $groupComponents=@()
 if($interfaceGroupCount -gt $groupId -and $interfaceGroupCount -lt 10000) {
  $bankGroup=$interfaceGroups+24*$groupId
  $bankComponentCount=Read-ClientQword ($bankGroup+8)
  $bankComponentArray=Read-ClientQword ($bankGroup+16)
  if($bankComponentCount -ge 0 -and $bankComponentCount -le 2048) {
   $groupComponents=@(for($componentIndex=0;$componentIndex -lt $bankComponentCount;$componentIndex++) {
    $componentPointer=Read-ClientQword ($bankComponentArray+16*$componentIndex+8)
    if($componentPointer -eq 0) {continue}
    if($groupId -eq 15) {
     $childCount=Read-ClientQword ($componentPointer+2896)
     $childArray=Read-ClientQword ($componentPointer+2904)
     if($childCount -ge 0 -and $childCount -le 2048) {
      for($childIndex=0;$childIndex -lt $childCount;$childIndex++) {
       $child=Read-ClientQword ($childArray+16*$childIndex+8)
       if($child -eq 0) {continue}
       $childItemId=Read-ClientDword ($child+2872)
       if($childItemId -ge 0) {
        $bankInventorySlots.Add([pscustomobject]@{ParentIndex=$componentIndex;Id=(Read-ClientDword ($child+4));SubId=(Read-ClientDword ($child+8));ItemId=$childItemId;ItemCount=(Read-ClientDword ($child+2876));X=(Read-ClientDword ($child+92));Y=(Read-ClientDword ($child+96));Width=(Read-ClientDword ($child+100));Height=(Read-ClientDword ($child+104));RenderCycle=(Read-ClientDword ($child+2936));CoordinateSpace='relative widget coordinates'})
       }
      }
     }
    }
    $componentText=Read-ClientString ($componentPointer+344)
    $baseOpName=Read-ClientString ($componentPointer+704)
    $componentOpCount=Read-ClientQword ($componentPointer+736)
    $componentOpArray=Read-ClientQword ($componentPointer+744)
    $componentOps=@(if($componentOpCount -ge 0 -and $componentOpCount -le 20) {for($componentOpIndex=0;$componentOpIndex -lt $componentOpCount;$componentOpIndex++){Read-ClientString ($componentOpArray+24*$componentOpIndex)}})
    if($componentText.Length -gt 0 -or $baseOpName.Length -gt 0 -or $componentIndex -eq 0 -or $componentOps.Count -gt 0 -or $groupId -eq 15) {
     [pscustomobject]@{Group=$groupId;Index=$componentIndex;Id=(Read-ClientDword ($componentPointer+4));Parent=(Read-ClientDword ($componentPointer+116));ItemId=(Read-ClientDword ($componentPointer+2872));ItemCount=(Read-ClientDword ($componentPointer+2876));Hidden=(Read-ClientBytes ($componentPointer+120) 1)[0];LastProcess=(Read-ClientDword ($componentPointer+56));RenderCycle=(Read-ClientDword ($componentPointer+2936));Text=$componentText;BaseOpName=$baseOpName;Ops=$componentOps;X=(Read-ClientDword ($componentPointer+92));Y=(Read-ClientDword ($componentPointer+96));Width=(Read-ClientDword ($componentPointer+100));Height=(Read-ClientDword ($componentPointer+104))}
    }
   })
  }
 }
 if($groupId -eq 12) {$bankComponents=$groupComponents} else {$bankInventoryComponents=$groupComponents}
 }
 $worldBuckets = Read-ClientQword ($clientState + 51688)
 $worldCount = Read-ClientDword ($clientState + 51696)
 if ($worldCount -lt 1 -or $worldCount -gt 65536) { throw 'Invalid world bucket count' }
 $worldSentinel = Read-ClientQword ($worldBuckets+8*$worldCount)
 $seenWorlds = [Collections.Generic.HashSet[long]]::new()
 $players = @(for ($bucketIndex=0; $bucketIndex -lt $worldCount; $bucketIndex++) {
  $worldNode = Read-ClientQword ($worldBuckets+8*$bucketIndex)
  for ($chainIndex=0; $worldNode -ne 0 -and $worldNode -ne $worldSentinel -and $chainIndex -lt 256; $chainIndex++) {
   if (-not $seenWorlds.Add($worldNode)) { break }
   $worldInstance = Read-ClientQword ($worldNode+16)
   $playerBuckets = Read-ClientQword ($worldInstance+104)
   $playerBucketCount = Read-ClientDword ($worldInstance+112)
   if ($playerBucketCount -ge 1 -and $playerBucketCount -le 65536) {
    $playerSentinel = Read-ClientQword ($playerBuckets+8*$playerBucketCount)
    $playerNode = Read-ClientQword ($playerBuckets+8*($localIndex%$playerBucketCount))
    for ($playerChainIndex=0; $playerNode -ne 0 -and $playerNode -ne $playerSentinel -and $playerChainIndex -lt 256; $playerChainIndex++) {
     if ((Read-ClientDword $playerNode) -eq $localIndex) {
      $playerObject = Read-ClientQword ($playerNode+16)
      if ($playerObject -ne 0) {
       $baseX = Read-ClientDword ($worldInstance+36)
       $baseY = Read-ClientDword ($worldInstance+40)
       $localX = Read-ClientDword ($playerObject+1008)
       $localY = Read-ClientDword ($playerObject+1048)
       $scenePointer = Read-ClientQword ($worldInstance+16)
       $sceneX=Read-ClientDword ($scenePointer+2376)
       $sceneY=Read-ClientDword ($scenePointer+2380)
       $plane=Read-ClientDword ($worldInstance+24)
       if($sceneX -ge 1 -and $sceneX -le 256 -and $sceneY -ge 1 -and $sceneY -le 256 -and $plane -ge 0 -and $plane -lt 4) {
        $tileArray=Read-ClientQword ($scenePointer+2408)
        $seenObjects=[Collections.Generic.HashSet[long]]::new()
        for($tileX=[Math]::Max(0,$localX-25);$tileX -le [Math]::Min($sceneX-1,$localX+25);$tileX++) {
         for($tileY=[Math]::Max(0,$localY-25);$tileY -le [Math]::Min($sceneY-1,$localY+25);$tileY++) {
          $tilePointer=Read-ClientQword ($tileArray+16*($tileY+$sceneY*($tileX+$sceneX*$plane))+8)
          if($tilePointer -eq 0) {continue}
          $objectsOnTile=Read-ClientDword ($tilePointer+52)
          if($objectsOnTile -lt 0 -or $objectsOnTile -gt 50) {continue}
          $objectArray=Read-ClientQword ($tilePointer+56)
          for($tileObjectIndex=0;$tileObjectIndex -lt $objectsOnTile;$tileObjectIndex++) {
           $sceneObject=Read-ClientQword ($objectArray+16*$tileObjectIndex+8)
           if($sceneObject -eq 0 -or -not $seenObjects.Add($sceneObject)) {continue}
           $tag=[BitConverter]::ToUInt64((Read-ClientBytes ($sceneObject+496) 8),0)
           if((($tag -shr 16) -band 7) -ne 2) {continue}
           $typeId=[int](($tag -shr 20) -band 65535)
           $definition=Read-LocDefinition $typeId
           if($definition.Name -match 'tree|bank|booth|stump|door' -or $definition.Ops -contains 'Chop down' -or $definition.Ops -contains 'Bank') {
            $objectX=Read-ClientDword ($sceneObject+528)
            $objectY=Read-ClientDword ($sceneObject+536)
            $objectEndX=Read-ClientDword ($sceneObject+532)
            $objectEndY=Read-ClientDword ($sceneObject+540)
            $heightArray=Read-ClientQword ($scenePointer+976)
            $floorHeight=Read-ClientDword ($heightArray+4*($objectY+($objectX+$plane*($sceneX+1))*($sceneY+1)))
            $fineX=64*($objectX+$objectEndX+1)
            $fineZ=64*($objectY+$objectEndY+1)
            $candidatePoint=Project-ScenePoint $scenePointer $fineX ($floorHeight-100) $fineZ
            $nearbyObjects.Add([pscustomobject]@{TypeId=$typeId;Name=$definition.Name;Ops=$definition.Ops;WorldX=$baseX+$objectX;WorldY=$baseY+$objectY;Pointer=('0x{0:X}' -f $sceneObject);ScreenPoint=$candidatePoint})
           }
          }
         }
        }
       }
       [pscustomobject]@{WorldId=(Read-ClientDword $worldNode);WorldPointer=('0x{0:X}' -f $worldInstance);PlayerPointer=('0x{0:X}' -f $playerObject);RouteLength=(Read-ClientDword ($playerObject+1004));LocalX=$localX;LocalY=$localY;BaseX=$baseX;BaseY=$baseY;WorldX=$baseX+$localX;WorldY=$baseY+$localY;ActionAnimation=(Read-ClientDword ($playerObject+1240));ScenePointer=('0x{0:X}' -f $scenePointer);SceneSizeX=(Read-ClientDword ($scenePointer+2376));SceneSizeY=(Read-ClientDword ($scenePointer+2380));TileArray=('0x{0:X}' -f (Read-ClientQword ($scenePointer+2408)))}
      }
      break
     }
     $playerNode = Read-ClientQword ($playerNode+24)
    }
   }
   $worldNode = Read-ClientQword ($worldNode+24)
  }
 })
 $menuEntries=@()
 $menuRoot=Read-ClientQword ($clientState+4273152)
 $nativeMenuPointerPoint=$null
 $defaultMenuCandidate=$null
 if($menuRoot -ne 0) {
  $menuInput=Read-ClientQword ($menuRoot+2168)
  if($menuInput -ne 0) {$nativeMenuPointerPoint=[pscustomobject]@{X=(Read-ClientDword ($menuInput+44));Y=(Read-ClientDword ($menuInput+48));Validation='Coordinates consumed by native tile menu builder; screen space pending confirmation'}}
  $menuBegin=Read-ClientQword ($menuRoot+552)
  $menuEnd=Read-ClientQword ($menuRoot+560)
  $menuBytes=$menuEnd-$menuBegin
  if($menuBytes -ge 0 -and $menuBytes -le 336*500 -and $menuBytes%336 -eq 0) {
   $menuEntries=@(for($menuIndex=0;$menuIndex -lt $menuBytes/336;$menuIndex++) {
    $entry=$menuBegin+336*$menuIndex
    $labels=@(foreach($labelOffset in @(80,184)) {
     $labelPointer=Read-ClientQword ($entry+$labelOffset)
     $labelLength=Read-ClientQword ($entry+$labelOffset+8)
     if($labelLength -eq 0) { '' }
     elseif($labelPointer -ne 0 -and $labelLength -gt 0 -and $labelLength -le 512) {
      [Text.Encoding]::UTF8.GetString((Read-ClientBytes $labelPointer $labelLength))
     } else { '<invalid label>' }
    })
    [pscustomobject]@{Index=$menuIndex;Target=$labels[0];Action=$labels[1];RawMetadata=@(foreach($metadataOffset in @(296,300,304,308,312,316,320)){Read-ClientDword ($entry+$metadataOffset)});Validation='Labels observed live; target metadata still under analysis'}
   })
  }
 }
 if($menuRoot -ne 0) {
  $orderedBegin=Read-ClientQword ($menuRoot+640)
  $orderedEnd=Read-ClientQword ($menuRoot+648)
  $orderedBytes=$orderedEnd-$orderedBegin
  if($orderedBytes -ge 24 -and $orderedBytes -le 24*500 -and $orderedBytes%24 -eq 0) {
   $orderedEntry=$orderedBegin
   for($orderedDepth=0;$orderedDepth -lt 8;$orderedDepth++) {
    $actionCollection=Read-ClientQword $orderedEntry
    if($actionCollection -ne 0) {
     $actionIndex=Read-ClientQword ($orderedEntry+8)
     $metadataBegin=Read-ClientQword ($actionCollection+24)
     $metadataEnd=Read-ClientQword ($actionCollection+32)
     $metadataSize=$metadataEnd-$metadataBegin
     if($metadataSize -ge 0 -and $metadataSize -le 336*500 -and $metadataSize%336 -eq 0 -and $actionIndex -ge 0 -and $actionIndex -lt $metadataSize/336) {
      $selected=$metadataBegin+336*$actionIndex
      $selectedLabels=@(foreach($selectedOffset in @(80,184)) {
       $selectedPointer=Read-ClientQword ($selected+$selectedOffset)
       $selectedLength=Read-ClientQword ($selected+$selectedOffset+8)
       if($selectedLength -eq 0) {''}
       elseif($selectedPointer -ne 0 -and $selectedLength -gt 0 -and $selectedLength -le 512) {[Text.Encoding]::UTF8.GetString((Read-ClientBytes $selectedPointer $selectedLength))}
       else {'<invalid label>'}
      })
      $defaultMenuCandidate=[pscustomobject]@{Target=$selectedLabels[0];Action=$selectedLabels[1];TargetId=(Read-ClientDword ($selected+296));SubId=(Read-ClientDword ($selected+300));OperationIndex=(Read-ClientDword ($selected+308));WorldId=(Read-ClientDword ($selected+312));WorldX=(Read-ClientDword ($selected+316));WorldY=(Read-ClientDword ($selected+320));ClientMenuSetting=(Read-ClientBytes ($clientState+4273136) 1)[0];Flags327=(Read-ClientBytes ($selected+327) 1)[0];Flags328=(Read-ClientBytes ($selected+328) 1)[0];Validation='Native ordered first leaf; input/settings may still open context menu'}
     }
     break
    }
    $nested=Read-ClientQword ($orderedEntry+16)
    if($nested -eq 0) {break}
    $nestedBegin=Read-ClientQword $nested
    $nestedEnd=Read-ClientQword ($nested+8)
    if($nestedEnd-$nestedBegin -lt 24 -or $nestedEnd-$nestedBegin -gt 24*500 -or ($nestedEnd-$nestedBegin)%24 -ne 0) {break}
    $orderedEntry=$nestedBegin
   }
  }
 }
 $hookDiagnostics=$null
 $hookOwner=Read-ClientQword ($clientBase+0x154F070)
 if($hookOwner -ne 0) {
  $hookOwnerVtable=Read-ClientQword $hookOwner
  $hookWindowGetter=Read-ClientQword ($hookOwnerVtable+88)
  $hookDiagnostics=[pscustomobject]@{Owner=('0x{0:X}' -f $hookOwner);WindowGetterRva=('0x{0:X}' -f ($hookWindowGetter-$clientBase))}
  if($hookWindowGetter-$clientBase -eq 0x2A1D0) {
   $hookWindow=Read-ClientQword ($hookOwner+100016)
   $hookDispatcher=Read-ClientQword ($hookWindow+248)
   $hookDispatcherVtable=Read-ClientQword $hookDispatcher
   $hookDispatcherGetter=Read-ClientQword ($hookDispatcherVtable+80)
   $hookDiagnostics | Add-Member -NotePropertyName DispatcherGetterRva -NotePropertyValue ('0x{0:X}' -f ($hookDispatcherGetter-$clientBase))
   if($hookDispatcherGetter-$clientBase -eq 0x38EE0) {
    $hookEventManager=$hookDispatcher+123260216
    $fallbackHandler=Read-ClientQword ($hookEventManager+8)
    $hookCallbacks=@(foreach($callbackKind in @('Movement','Button')) {
     $callbackOffset=if($callbackKind -eq 'Movement'){2192}else{2088}
     if($fallbackHandler -eq 0){continue}
     $callbackBegin=Read-ClientQword ($fallbackHandler+$callbackOffset)
     $callbackEnd=Read-ClientQword ($fallbackHandler+$callbackOffset+8)
     if($callbackEnd-$callbackBegin -lt 0 -or $callbackEnd-$callbackBegin -gt 8*128){continue}
     for($callbackSlot=$callbackBegin;$callbackSlot -lt $callbackEnd;$callbackSlot+=8) {
      $callbackWrapper=Read-ClientQword $callbackSlot
      if($callbackWrapper -eq 0){continue}
      $callbackCallable=Read-ClientQword ($callbackWrapper+56)
      if($callbackCallable -eq 0){continue}
      $callbackVtable=Read-ClientQword $callbackCallable
      $callbackInvoke=Read-ClientQword ($callbackVtable+16)
      $callbackTarget=Read-ClientQword ($callbackCallable+8)
      $callbackContext=Read-ClientQword ($callbackCallable+24)
      $inputBackend=Read-ClientQword $callbackContext
      $inputBackendVtable=Read-ClientQword $inputBackend
      $inputMethodOffset=if($callbackKind -eq 'Movement'){112}else{104}
      $inputMethod=Read-ClientQword ($inputBackendVtable+$inputMethodOffset)
      $listenerMethods=[Collections.Generic.List[string]]::new()
      $listenerStack=[Collections.Generic.Stack[long]]::new()
      $listenerSeen=[Collections.Generic.HashSet[long]]::new()
      $listenerStack.Push((Read-ClientQword ($inputBackend+8)))
      while($listenerStack.Count -gt 0 -and $listenerSeen.Count -lt 128) {
       $listenerNode=$listenerStack.Pop()
       if($listenerNode -eq 0 -or $listenerNode -eq $inputBackend+8 -or -not $listenerSeen.Add($listenerNode)){continue}
       $listenerObject=Read-ClientQword ($listenerNode+40)
       if($listenerObject -ne 0) {
        $listenerVtable=Read-ClientQword $listenerObject
        $listenerMethod=Read-ClientQword ($listenerVtable+$inputMethodOffset)
        $listenerMethods.Add(('0x{0:X}' -f ($listenerMethod-$clientBase)))
       }
       $listenerStack.Push((Read-ClientQword $listenerNode))
       $listenerStack.Push((Read-ClientQword ($listenerNode+8)))
      }
      $hookDiagnostics | Add-Member -NotePropertyName ($callbackKind+'ListenerMethods') -NotePropertyValue $listenerMethods -Force
      $eventListenerNode=Read-ClientQword ($inputBackend+16)
      if($eventListenerNode -ne $inputBackend+8) {
       $eventListener=Read-ClientQword ($eventListenerNode+40)
       if($eventListener -ne 0) {
        $eventListenerVtable=Read-ClientQword $eventListener
        $eventListenerMethod=Read-ClientQword ($eventListenerVtable+$inputMethodOffset)
        $hookDiagnostics | Add-Member -NotePropertyName ($callbackKind+'ListenerRva') -NotePropertyValue ('0x{0:X}' -f ($eventListenerMethod-$clientBase)) -Force
       }
      }
      [pscustomobject]@{Kind=$callbackKind;InvokeRva=('0x{0:X}' -f ($callbackInvoke-$clientBase));TargetRva=('0x{0:X}' -f ($callbackTarget-$clientBase));InputMethodRva=('0x{0:X}' -f ($inputMethod-$clientBase))}
     }
    })
    $hookDiagnostics | Add-Member -NotePropertyName Callbacks -NotePropertyValue $hookCallbacks
   }
  }
 }

 $bankRoot=$bankComponents | Where-Object Index -eq 0 | Select-Object -First 1
 $hoveredSceneTargets=@(foreach($menuEntry in $menuEntries) {
  if($menuEntry.Action -ne 'Chop down' -and $menuEntry.Action -ne 'Bank') {continue}
  $matchedObjects=@($nearbyObjects | Where-Object { $_.TypeId -eq $menuEntry.RawMetadata[0] -and $_.WorldX -eq $menuEntry.RawMetadata[5] -and $_.WorldY -eq $menuEntry.RawMetadata[6] })
  foreach($matchedObject in $matchedObjects) {
   [pscustomobject]@{TypeId=$matchedObject.TypeId;Name=$matchedObject.Name;WorldX=$matchedObject.WorldX;WorldY=$matchedObject.WorldY;Action=$menuEntry.Action;RegularTree=($matchedObject.TypeId -in @(1276,1278) -and $menuEntry.Action -eq 'Chop down');VarrockWestBankBooth=($matchedObject.TypeId -eq 10583 -and $matchedObject.WorldX -eq 3186 -and $matchedObject.WorldY -in @(3438,3440,3442,3444));PointerPoint=$nativeMenuPointerPoint;ProjectedPoint=$matchedObject.ScreenPoint;Validation='Scene identity matched to native hover menu; snapshot is not atomic'}
  }
 })
 $bankSlotTargets=@()
 $inventoryContainer=$containers | Where-Object ContainerId -eq 93 | Select-Object -First 1
 $inventoryGroupCoordinates=$bankGroupCoordinates | Where-Object Group -eq 15 | Select-Object -First 1
 if($inventoryGroupCoordinates -and $inventoryContainer -and $bankRoot -and $bankRoot.LastProcess -gt 0 -and $bankRoot.Width -gt 0 -and $bankRoot.Height -gt 0) {
  $bankSlotTargets=@(foreach($slotWidget in $bankInventorySlots) {
   if($slotWidget.ParentIndex -ne 3) {continue}
   $actualSlot=$inventoryContainer.Items | Where-Object Slot -eq $slotWidget.SubId | Select-Object -First 1
   if(-not $actualSlot -or $actualSlot.ItemId -ne $slotWidget.ItemId) {continue}
   $left=$inventoryGroupCoordinates.RawDwords[0]+$slotWidget.X
   $top=$inventoryGroupCoordinates.RawDwords[1]+$slotWidget.Y
   $matchingActions=@($menuEntries | Where-Object { $_.RawMetadata[0] -eq $slotWidget.Id -and $_.RawMetadata[1] -eq $slotWidget.SubId })
   $hoverActionNames=@($matchingActions | ForEach-Object { $_.Action })
   $pointerInside=$null -ne $nativeMenuPointerPoint -and $nativeMenuPointerPoint.X -ge $left -and $nativeMenuPointerPoint.X -lt $left+$slotWidget.Width -and $nativeMenuPointerPoint.Y -ge $top -and $nativeMenuPointerPoint.Y -lt $top+$slotWidget.Height
   [pscustomobject]@{Slot=$actualSlot.Slot;ItemId=$actualSlot.ItemId;Quantity=$actualSlot.Quantity;RegularLog=($actualSlot.ItemId -eq 1511);Left=$left;Top=$top;Width=$slotWidget.Width;Height=$slotWidget.Height;CenterX=$left+[int]($slotWidget.Width/2);CenterY=$top+[int]($slotWidget.Height/2);PointerInside=$pointerInside;HoverActions=$hoverActionNames;Validation='Observed bank layout at 1:1 rendering; revalidate after UI or scale changes'}
  })
 }
 $cursorPoint=[ClientMemoryReader+Point]::new()
 $windowGeometry=$null
 $clientOrigin=[ClientMemoryReader+Point]::new()
 $clientRect=[ClientMemoryReader+Rect]::new()
 $windowRect=[ClientMemoryReader+Rect]::new()
 $windowHandle=$clientProcess.MainWindowHandle
 if($windowHandle -ne [IntPtr]::Zero -and [ClientMemoryReader]::GetClientRect($windowHandle,[ref]$clientRect) -and [ClientMemoryReader]::GetWindowRect($windowHandle,[ref]$windowRect) -and [ClientMemoryReader]::ClientToScreen($windowHandle,[ref]$clientOrigin)) {
  $windowGeometry=[pscustomobject]@{ClientScreenX=$clientOrigin.X;ClientScreenY=$clientOrigin.Y;ClientWidth=$clientRect.Right-$clientRect.Left;ClientHeight=$clientRect.Bottom-$clientRect.Top;WindowScreenX=$windowRect.Left;WindowScreenY=$windowRect.Top;ClientOffsetX=$clientOrigin.X-$windowRect.Left;ClientOffsetY=$clientOrigin.Y-$windowRect.Top;Validation='Read-only Windows geometry; require dimensions and DPI agreement before input'}
 }
 $clientCursor=$null
 if([ClientMemoryReader]::GetCursorPos([ref]$cursorPoint) -and [ClientMemoryReader]::ScreenToClient($clientProcess.MainWindowHandle,[ref]$cursorPoint)) {
  $clientCursor=[pscustomobject]@{X=$cursorPoint.X;Y=$cursorPoint.Y;CoordinateSpace='client area pixels'}
 }
 $bankOpenObserved=$null -ne $bankRoot -and $bankRoot.LastProcess -gt 0 -and $bankRoot.Width -gt 0 -and $bankRoot.Height -gt 0
 [pscustomobject]@{ProcessId=$ClientProcessId;ModuleBase=('0x{0:X}' -f $clientBase);ClientState=('0x{0:X}' -f $clientState);LocalPlayerIndex=$localIndex;Woodcutting=$stats[8];Containers=$containers;Players=$players;NearbyObjects=$nearbyObjects;BankOpenObserved=$bankOpenObserved;CurrentRenderCycle=$currentRenderCycle;BankComponents=$bankComponents;BankInventoryComponents=$bankInventoryComponents;BankInventorySlots=$bankInventorySlots;BankSlotTargets=$bankSlotTargets;BankGroupCoordinates=$bankGroupCoordinates;MenuEntries=$menuEntries;DefaultMenuCandidate=$defaultMenuCandidate;HoveredSceneTargets=$hoveredSceneTargets;NativeMenuPointerPoint=$nativeMenuPointerPoint;ClientCursor=$clientCursor;WindowGeometry=$windowGeometry;InputHookDiagnostics=$hookDiagnostics;RenderInfo=$renderInfo} | ConvertTo-Json -Depth 7
} finally { [void][ClientMemoryReader]::CloseHandle($clientHandle) }
