using '../main.bicep'

param environment = 'prod'
param location = 'eastus2'
param vnetAddressPrefix = '10.62.0.0/16'
param caeSubnetPrefix = '10.62.0.0/23'
param peSubnetPrefix = '10.62.2.0/26'
param corpVpnCidr = '10.251.0.0/20'

param postgresServerId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-prod/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-kallicode-prod'
param blobStorageAccountId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-prod/providers/Microsoft.Storage/storageAccounts/stkallicodeadminprd'
param keyVaultId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-prod/providers/Microsoft.KeyVault/vaults/kv-kallicode-admin-prd'
param keyVaultUri = 'https://kv-kallicode-admin-prd.vault.azure.net/'
param redisCacheId = '/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-kallicode-prod/providers/Microsoft.Cache/Redis/redis-kallicode-prod'

param apiImage = 'acrkallicodeprd.azurecr.io/kallicode-admin-api:v0.1.0'
param webImage = 'acrkallicodeprd.azurecr.io/kallicode-admin-web:v0.1.0'
param workerImage = 'acrkallicodeprd.azurecr.io/kallicode-admin-workers:v0.1.0'

param adminHostname = 'admin.internal.kallicode.com'
param corsOrigins = 'https://admin.internal.kallicode.com'
param telemetryBaseUrl = 'https://telemetry.internal.kallicode.com/internal/v1'
param blobAccountUrl = 'https://stkallicodeadminprd.blob.core.windows.net'

param apiMinReplicas = 2
param apiMaxReplicas = 6
