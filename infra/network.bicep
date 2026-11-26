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

@description('Prefijo CIDR (/23 o mayor capacidad) para la subred delegada a Container Apps.')
param caeSubnetPrefix string

@description('Prefijo CIDR para la subred dedicada a Private Endpoints.')
param peSubnetPrefix string

@description('Rango CIDR autorizado de la VPN corporativa / peering administrativo de KalliCode.')
param corpVpnCidr string

@description('ID del recurso Azure Database for PostgreSQL Flexible Server.')
param postgresServerId string

@description('ID del recurso Azure Storage Account para informes exportables.')
param blobStorageAccountId string

@description('ID del recurso Azure Key Vault con claves JWT y cadenas de conexión.')
param keyVaultId string

@description('ID del recurso Azure Cache for Redis para sesiones staff y rate limiting.')
param redisCacheId string

@description('Etiquetas de gobierno y trazabilidad.')
param tags object = {}

var baseName = 'kc-admin-${environment}'
var defaultTags = union({
  service: 'kallicode-admin'
  environment: environment
  securityControl: 'ADM-G10-zero-public-ingress'
}, tags)

// NSG de la subred del Container Apps Environment:
// bloquea explícitamente todo tráfico entrante desde Internet y restringe el acceso
// exclusivamente a la VPN corporativa de KalliCode y al tráfico intra-VNet.
resource nsgCae 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${baseName}-cae'
  location: location
  tags: defaultTags
  properties: {
    securityRules: [
      {
        name: 'AllowCorpVpnHttpsInbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: corpVpnCidr
          sourcePortRange: '*'
          destinationAddressPrefix: caeSubnetPrefix
          destinationPortRange: '443'
          description: 'Permite acceso HTTPS administrativo exclusivamente desde la VPN corporativa de KalliCode.'
        }
      }
      {
        name: 'AllowVnetInternalInbound'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRange: '*'
          description: 'Comunicación intra-VNet entre plano de control interno, API, workers y sondas.'
        }
      }
      {
        name: 'DenyAllInternetInbound'
        properties: {
          priority: 4090
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
          description: 'Bloqueo estricto ADM-G10: deniega todo tráfico entrante desde Internet.'
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
          description: 'Denegación por defecto ante cualquier origen distinto de VPN corporativa o VNet privada.'
        }
      }
      {
        name: 'AllowPrivateEndpointsOutbound'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: caeSubnetPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: peSubnetPrefix
          destinationPortRanges: [
            '443'
            '5432'
            '6380'
          ]
          description: 'Salida privada hacia PostgreSQL, Blob Storage, Key Vault y Redis via Private Endpoints.'
        }
      }
      {
        name: 'DenyInternetOutbound'
        properties: {
          priority: 4090
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '*'
          description: 'Evita exfiltración o comunicación saliente por red pública.'
        }
      }
    ]
  }
}

// NSG de la subred de Private Endpoints: solo acepta tráfico desde la VNet privada.
resource nsgPe 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: 'nsg-${baseName}-pe'
  location: location
  tags: defaultTags
  properties: {
    securityRules: [
      {
        name: 'AllowCaeToPrivateEndpointsInbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: caeSubnetPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: peSubnetPrefix
          destinationPortRanges: [
            '443'
            '5432'
            '6380'
          ]
          description: 'Acepta conexiones privadas únicamente desde la subred delegada de Container Apps.'
        }
      }
      {
        name: 'DenyAllInternetInbound'
        properties: {
          priority: 4090
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
          description: 'Bloqueo estricto de tráfico desde Internet hacia los Private Endpoints.'
        }
      }
    ]
  }
}

// VNet privada exclusiva de la consola de administración (sin IP pública ni ingress compartido).
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: 'vnet-${baseName}'
  location: location
  tags: defaultTags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: 'snet-admin-cae'
        properties: {
          addressPrefix: caeSubnetPrefix
          networkSecurityGroup: {
            id: nsgCae.id
          }
          delegations: [
            {
              name: 'delegation-container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
          privateEndpointNetworkPolicies: 'Enabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
      {
        name: 'snet-admin-pe'
        properties: {
          addressPrefix: peSubnetPrefix
          networkSecurityGroup: {
            id: nsgPe.id
          }
          privateEndpointNetworkPolicies: 'Disabled'
          privateLinkServiceNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

var caeSubnetId = vnet.properties.subnets[0].id
var peSubnetId = vnet.properties.subnets[1].id

// Zonas Private DNS privadas para que el tráfico nunca salga a resolución pública.
var privateDnsSpecs = [
  {
    key: 'postgres'
    zoneName: 'privatelink.postgres.database.azure.com'
  }
  {
    key: 'blob'
    zoneName: 'privatelink.blob.core.windows.net'
  }
  {
    key: 'vault'
    zoneName: 'privatelink.vaultcore.net'
  }
  {
    key: 'redis'
    zoneName: 'privatelink.redis.cache.windows.net'
  }
]

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for spec in privateDnsSpecs: {
  name: spec.zoneName
  location: 'global'
  tags: defaultTags
}]

resource privateDnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = [for (spec, idx) in privateDnsSpecs: {
  parent: privateDnsZones[idx]
  name: 'link-${baseName}-${spec.key}'
  location: 'global'
  tags: defaultTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

// Private Endpoints hacia servicios gestionados.
resource pePostgres 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${baseName}-postgres'
  location: location
  tags: defaultTags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${baseName}-postgres'
        properties: {
          privateLinkServiceId: postgresServerId
          groupIds: [
            'postgresqlServer'
          ]
        }
      }
    ]
  }
}

resource pePostgresDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: pePostgres
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'postgres-zone'
        properties: {
          privateDnsZoneId: privateDnsZones[0].id
        }
      }
    ]
  }
}

resource peBlob 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${baseName}-blob'
  location: location
  tags: defaultTags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${baseName}-blob'
        properties: {
          privateLinkServiceId: blobStorageAccountId
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource peBlobDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peBlob
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob-zone'
        properties: {
          privateDnsZoneId: privateDnsZones[1].id
        }
      }
    ]
  }
}

resource peKeyVault 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${baseName}-kv'
  location: location
  tags: defaultTags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${baseName}-kv'
        properties: {
          privateLinkServiceId: keyVaultId
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource peKeyVaultDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peKeyVault
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'kv-zone'
        properties: {
          privateDnsZoneId: privateDnsZones[2].id
        }
      }
    ]
  }
}

resource peRedis 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: 'pe-${baseName}-redis'
  location: location
  tags: defaultTags
  properties: {
    subnet: {
      id: peSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${baseName}-redis'
        properties: {
          privateLinkServiceId: redisCacheId
          groupIds: [
            'redisCache'
          ]
        }
      }
    ]
  }
}

resource peRedisDnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: peRedis
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis-zone'
        properties: {
          privateDnsZoneId: privateDnsZones[3].id
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output caeSubnetId string = caeSubnetId
output peSubnetId string = peSubnetId
output nsgCaeId string = nsgCae.id
output nsgPeId string = nsgPe.id
