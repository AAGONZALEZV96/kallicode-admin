@description('Entorno objetivo de despliegue (nunca público).')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string

@description('Región Azure del despliegue.')
param location string = resourceGroup().location

@description('Prefijo CIDR privado RFC 1918 de la VNet exclusiva de kallicode-admin.')
param vnetAddressPrefix string

@description('Prefijo CIDR para la subred delegada a Container Apps.')
param caeSubnetPrefix string

@description('Prefijo CIDR para la subred de Private Endpoints.')
param peSubnetPrefix string

@description('Rango CIDR autorizado de la VPN corporativa de KalliCode.')
param corpVpnCidr string

@description('ID del servidor PostgreSQL Flexible Server.')
param postgresServerId string

@description('ID de la cuenta Azure Storage.')
param blobStorageAccountId string

@description('ID del Azure Key Vault.')
param keyVaultId string

@description('URI del Azure Key Vault.')
param keyVaultUri string

@description('ID de Azure Cache for Redis.')
param redisCacheId string

@description('Imagen de contenedor de la API FastAPI (/admin/v1).')
param apiImage string

@description('Imagen de contenedor del frontend web interno (apps/web).')
param webImage string

@description('Imagen de contenedor de los workers internos.')
param workerImage string

@description('Hostname interno privado asignado a la consola en Private DNS.')
param adminHostname string

@description('Orígenes CORS explícitos (sin comodines).')
param corsOrigins string

@description('URL base privada de telemetría del pipeline.')
param telemetryBaseUrl string

@description('URL privada de Azure Blob Storage.')
param blobAccountUrl string

@description('Versión de la aplicación.')
param appVersion string = '0.1.0'

@description('Mínimo de réplicas para la API.')
@minValue(1)
param apiMinReplicas int = 1

@description('Máximo de réplicas para la API.')
@minValue(1)
param apiMaxReplicas int = 3

@description('Etiquetas de gobierno.')
param tags object = {}

module network './network.bicep' = {
  name: 'deploy-network-${environment}'
  params: {
    environment: environment
    location: location
    vnetAddressPrefix: vnetAddressPrefix
    caeSubnetPrefix: caeSubnetPrefix
    peSubnetPrefix: peSubnetPrefix
    corpVpnCidr: corpVpnCidr
    postgresServerId: postgresServerId
    blobStorageAccountId: blobStorageAccountId
    keyVaultId: keyVaultId
    redisCacheId: redisCacheId
    tags: tags
  }
}

module containerApps './containerapps.bicep' = {
  name: 'deploy-containerapps-${environment}'
  params: {
    environment: environment
    location: location
    vnetId: network.outputs.vnetId
    caeSubnetId: network.outputs.caeSubnetId
    caeSubnetPrefix: caeSubnetPrefix
    apiImage: apiImage
    webImage: webImage
    workerImage: workerImage
    adminHostname: adminHostname
    corsOrigins: corsOrigins
    telemetryBaseUrl: telemetryBaseUrl
    blobAccountUrl: blobAccountUrl
    keyVaultUri: keyVaultUri
    appVersion: appVersion
    apiMinReplicas: apiMinReplicas
    apiMaxReplicas: apiMaxReplicas
    tags: tags
  }
}

output vnetId string = network.outputs.vnetId
output managedEnvironmentId string = containerApps.outputs.managedEnvironmentId
output managedEnvironmentStaticIp string = containerApps.outputs.managedEnvironmentStaticIp
output apiInternalFqdn string = containerApps.outputs.apiInternalFqdn
output webInternalFqdn string = containerApps.outputs.webInternalFqdn
