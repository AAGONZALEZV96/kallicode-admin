using '../main.bicep'

param environment = 'staging'
param location = 'eastus2'
param vnetAddressPrefix = '10.61.0.0/16'
param caeSubnetPrefix = '10.61.0.0/23'
param peSubnetPrefix = '10.61.2.0/26'
param corpVpnCidr = '10.250.0.0/16'

param postgresServerId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-staging/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-kallicode-staging'
param blobStorageAccountId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-staging/providers/Microsoft.Storage/storageAccounts/stkallicodeadminstg'
param keyVaultId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-staging/providers/Microsoft.KeyVault/vaults/kv-kallicode-admin-stg'
param keyVaultUri = 'https://kv-kallicode-admin-stg.vault.azure.net/'
param redisCacheId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-staging/providers/Microsoft.Cache/Redis/redis-kallicode-staging'

param apiImage = 'acrkallicodestg.azurecr.io/kallicode-admin-api:staging'
param webImage = 'acrkallicodestg.azurecr.io/kallicode-admin-web:staging'
param workerImage = 'acrkallicodestg.azurecr.io/kallicode-admin-workers:staging'

param adminHostname = 'admin-staging.internal.kallicode.com'
param corsOrigins = 'https://admin-staging.internal.kallicode.com'
param telemetryBaseUrl = 'https://telemetry-staging.internal.kallicode.com/internal/v1'
param blobAccountUrl = 'https://stkallicodeadminstg.blob.core.windows.net'

param apiMinReplicas = 1
param apiMaxReplicas = 3
