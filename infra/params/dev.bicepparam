using '../main.bicep'

param environment = 'dev'
param location = 'eastus2'
param vnetAddressPrefix = '10.60.0.0/16'
param caeSubnetPrefix = '10.60.0.0/23'
param peSubnetPrefix = '10.60.2.0/26'
param corpVpnCidr = '10.250.0.0/16'

param postgresServerId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-dev/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-kallicode-dev'
param blobStorageAccountId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-dev/providers/Microsoft.Storage/storageAccounts/stkallicodeadmindev'
param keyVaultId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-dev/providers/Microsoft.KeyVault/vaults/kv-kallicode-admin-dev'
param keyVaultUri = 'https://kv-kallicode-admin-dev.vault.azure.net/'
param redisCacheId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-dev/providers/Microsoft.Cache/Redis/redis-kallicode-dev'

param apiImage = 'acrkallicodedev.azurecr.io/kallicode-admin-api:dev'
param webImage = 'acrkallicodedev.azurecr.io/kallicode-admin-web:dev'
param workerImage = 'acrkallicodedev.azurecr.io/kallicode-admin-workers:dev'

param adminHostname = 'admin-dev.internal.kallicode.com'
param corsOrigins = 'https://admin-dev.internal.kallicode.com'
param telemetryBaseUrl = 'https://telemetry-dev.internal.kallicode.com/internal/v1'
param blobAccountUrl = 'https://stkallicodeadmindev.blob.core.windows.net'

param apiMinReplicas = 1
param apiMaxReplicas = 2
