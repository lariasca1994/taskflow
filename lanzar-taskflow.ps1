$compartmentId = "ocid1.tenancy.oc1..aaaaaaaaqsxqtjtk4gpsqwr2hdtoxyiglsem4rtbhpxj3ntotpr35hullfka"
$ad = "ZfMg:SA-BOGOTA-1-AD-1"
$subnetId = "ocid1.subnet.oc1.sa-bogota-1.aaaaaaaa4rgxu5lcnfmow5djmwkov47tsnwaswid3q6nzd5l6vpomppfj4iq"
$imageId = "ocid1.image.oc1.sa-bogota-1.aaaaaaaacy6qnr5jquww2zs33otv4dqulojclenqg4qra2j54cq2xskjzyiq"

$maxIntentos = 300
$esperaSegundos = 180
$estadoFile = "A:\Github\taskflow\estado-lanzamiento.txt"

for ($i = 1; $i -le $maxIntentos; $i++) {
    "Intento $i de $maxIntentos - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $estadoFile -Append

    oci compute instance launch `
        --compartment-id $compartmentId `
        --availability-domain $ad `
        --shape "VM.Standard.A1.Flex" `
        --shape-config file://A:\Github\taskflow\shape-config.json `
        --image-id $imageId `
        --subnet-id $subnetId `
        --assign-public-ip true `
        --display-name "taskflow-vm" `
        --ssh-authorized-keys-file "$env:USERPROFILE\.ssh\taskflow_oci.pub" `
        --user-data-file "A:\Github\taskflow\oci-deploy\cloud-init.sh" `
        --profile lufearca7 `
        --output json | Out-File "A:\Github\taskflow\instance-launched.json"

    if ($LASTEXITCODE -eq 0) {
        "EXITO en el intento $i - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File $estadoFile -Append
        break
    }

    Start-Sleep -Seconds $esperaSegundos
}