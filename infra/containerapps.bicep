@description('Entorno objetivo de despliegue.')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string

@description('Región Azure del despliegue.')
param location string = resourceGroup().location

@description('ID de la VNet privada exclusiva de la consola.')
param vnetId string

@description('ID de la subred delegada a Microsoft.App/environments.')
param caeSubnetId string

@description('CIDR exacto de la subred del Container Apps Environment (proxies confiables y scraping interno).')
param caeSubnetPrefix string

@description('Imagen de contenedor de la API FastAPI (/admin/v1).')
param apiImage string

@description('Imagen de contenedor del frontend web interno (apps/web).')
param webImage string

@description('Imagen de contenedor de los workers internos (admin_workers).')
param workerImage string

@description('Hostname interno único asignado a la consola administrativa en Private DNS.')
param adminHostname string

@description('Orígenes CORS explícitos permitidos (sin comodines, acorde a KC-ADM-B6-03).')
param corsOrigins string

@description('URL base del servicio interno de telemetría (Equipo 2).')
param telemetryBaseUrl string

@description('URL privada de la cuenta Blob Storage (sin devstoreaccount1).')
param blobAccountUrl string

@description('URI base del Azure Key Vault con los secretos de la consola.')
param keyVaultUri string

@description('Versión desplegada de la aplicación para /admin/v1/health.')
param appVersion string = '0.1.0'

@description('Número mínimo de réplicas de la API.')
@minValue(1)
param apiMinReplicas int = 1

@description('Número máximo de réplicas de la API.')
@minValue(1)
param apiMaxReplicas int = 3

@description('Etiquetas de gobierno y trazabilidad.')
param tags object = {}

var baseName = 'kc-admin-${environment}'
var defaultTags = union({
  service: 'kallicode-admin'
  environment: environment
  securityControl: 'ADM-G10-zero-public-ingress'
}, tags)

// Espacio de logs privado para trazabilidad operativa sin PII.
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${baseName}'
  location: location
  tags: defaultTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: environment == 'prod' ? 90 : 30
    publicNetworkAccessForIngestion: 'Disabled'
    publicNetworkAccessForQuery: 'Disabled'
  }
}

// Container Apps Environment estrictamente interno (ADM-G10):
// vnetConfiguration.internal = true y publicNetworkAccess = 'Disabled' son fijos.
resource managedEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${baseName}'
  location: location
  tags: defaultTags
  properties: {
    publicNetworkAccess: 'Disabled'
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: caeSubnetId
      internal: true
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    peerAuthentication: {
      mtls: {
        enabled: true
      }
    }
  }
}

// Private DNS Zone interna para resolver el dominio interno del CAE y adminHostname solo dentro de la VNet/VPN.
resource caePrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'internal.kallicode.com'
  location: 'global'
  tags: defaultTags
}

resource caePrivateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: caePrivateDnsZone
  name: 'link-${baseName}-internal-dns'
  location: 'global'
  tags: defaultTags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

var dnsRecordPrefix = split(adminHostname, '.')[0]

resource caePrivateDnsARecord 'Microsoft.Network/privateDnsZones/A@2020-06-01' = {
  parent: caePrivateDnsZone
  name: dnsRecordPrefix
  properties: {
    ttl: 300
    aRecords: [
      {
        ipv4Address: managedEnvironment.properties.staticIp
      }
    ]
  }
}

// API FastAPI (/admin/v1): ingress estrictamente interno (external: false).
resource apiApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${baseName}-api'
  location: location
  tags: defaultTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      secrets: [
        {
          name: 'kc-admin-db-app'
          keyVaultUrl: '${keyVaultUri}secrets/kc-admin-database-url-app'
          identity: 'system'
        }
        {
          name: 'kc-admin-db-ro'
          keyVaultUrl: '${keyVaultUri}secrets/kc-admin-database-url-ro'
          identity: 'system'
        }
        {
          name: 'kc-redis-url'
          keyVaultUrl: '${keyVaultUri}secrets/kc-redis-url'
          identity: 'system'
        }
        {
          name: 'kc-jwt-private-key'
          keyVaultUrl: '${keyVaultUri}secrets/kc-jwt-private-key'
          identity: 'system'
        }
        {
          name: 'kc-jwt-public-key'
          keyVaultUrl: '${keyVaultUri}secrets/kc-jwt-public-key'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'admin-api'
          image: apiImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'PORT'
              value: '8000'
            }
            {
              name: 'KC_ADMIN_ENV'
              value: environment
            }
            {
              name: 'KC_ADMIN_APP_VERSION'
              value: appVersion
            }
            {
              name: 'KC_ADMIN_DATABASE_URL_APP'
              secretRef: 'kc-admin-db-app'
            }
            {
              name: 'KC_ADMIN_DATABASE_URL_RO'
              secretRef: 'kc-admin-db-ro'
            }
            {
              name: 'KC_REDIS_URL'
              secretRef: 'kc-redis-url'
            }
            {
              name: 'KC_JWT_PRIVATE_KEY'
              secretRef: 'kc-jwt-private-key'
            }
            {
              name: 'KC_JWT_PUBLIC_KEY'
              secretRef: 'kc-jwt-public-key'
            }
            {
              name: 'KC_ADMIN_ALLOWED_HOSTS'
              value: adminHostname
            }
            {
              name: 'KC_ADMIN_CORS_ORIGINS'
              value: corsOrigins
            }
            {
              name: 'KC_ADMIN_TRUSTED_PROXIES'
              value: caeSubnetPrefix
            }
            {
              name: 'KC_ADMIN_TELEMETRY_BASE_URL'
              value: telemetryBaseUrl
            }
            {
              name: 'KC_BLOB_ACCOUNT_URL'
              value: blobAccountUrl
            }
            {
              name: 'KC_ADMIN_HEALTH_CHECK_BLOB_REMOTE'
              value: 'true'
            }
            {
              name: 'KC_ADMIN_METRICS_ENABLED'
              value: 'true'
            }
            {
              name: 'KC_ADMIN_METRICS_ALLOW_CIDRS'
              value: caeSubnetPrefix
            }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/admin/v1/health'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: [
                  {
                    name: 'Host'
                    value: adminHostname
                  }
                ]
              }
              initialDelaySeconds: 10
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/admin/v1/health'
                port: 8000
                scheme: 'HTTP'
                httpHeaders: [
                  {
                    name: 'Host'
                    value: adminHostname
                  }
                ]
              }
              initialDelaySeconds: 5
              periodSeconds: 15
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: apiMinReplicas
        maxReplicas: apiMaxReplicas
      }
    }
  }
}

// Interfaz Web SPA (apps/web): alojada en el mismo entorno interno con ingress.external = false.
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${baseName}-web'
  location: location
  tags: defaultTags
  properties: {
    managedEnvironmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8080
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'admin-web'
          image: webImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'VITE_ADMIN_API_BASE_URL'
              value: 'https://${adminHostname}/admin/v1'
            }
          ]
        }
      ]
      scale: {
        minReplicas: environment == 'prod' ? 2 : 1
        maxReplicas: environment == 'prod' ? 4 : 2
      }
    }
  }
}

// Workers internos (admin_workers): sin bloque ingress ni puerto HTTP público.
resource workerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: 'ca-${baseName}-workers'
  location: location
  tags: defaultTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [
        {
          name: 'kc-admin-db-app'
          keyVaultUrl: '${keyVaultUri}secrets/kc-admin-database-url-app'
          identity: 'system'
        }
        {
          name: 'kc-admin-db-ro'
          keyVaultUrl: '${keyVaultUri}secrets/kc-admin-database-url-ro'
          identity: 'system'
        }
        {
          name: 'kc-redis-url'
          keyVaultUrl: '${keyVaultUri}secrets/kc-redis-url'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'admin-workers'
          image: workerImage
          command: [
            'python'
            '-m'
            'admin_workers.main'
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'KC_ADMIN_ENV'
              value: environment
            }
            {
              name: 'KC_ADMIN_DATABASE_URL_APP'
              secretRef: 'kc-admin-db-app'
            }
            {
              name: 'KC_ADMIN_DATABASE_URL_RO'
              secretRef: 'kc-admin-db-ro'
            }
            {
              name: 'KC_REDIS_URL'
              secretRef: 'kc-redis-url'
            }
            {
              name: 'KC_BLOB_ACCOUNT_URL'
              value: blobAccountUrl
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: environment == 'prod' ? 2 : 1
      }
    }
  }
}

output managedEnvironmentId string = managedEnvironment.id
output managedEnvironmentDefaultDomain string = managedEnvironment.properties.defaultDomain
output managedEnvironmentStaticIp string = managedEnvironment.properties.staticIp
output apiInternalFqdn string = apiApp.properties.configuration.ingress.fqdn
output webInternalFqdn string = webApp.properties.configuration.ingress.fqdn
