@description('Azure region')
param location string = resourceGroup().location

@description('Project name prefix')
param projectName string = 'dsr-api'

@description('Environment name')
param environment string = 'dev'

@description('Container image name')
param containerImage string

@description('Partner API key used internally between APIM and backend')
@secure()
param partnerApiKey string

@description('Internal secret used to ensure backend only accepts requests from APIM')
@secure()
param backendInternalSecret string

@description('APIM publisher email')
param publisherEmail string

@description('APIM publisher name')
param publisherName string = 'DSR API Team'

var lawName = 'law-${projectName}-${environment}'
var acrName = replace('acr${projectName}${environment}', '-', '')
var containerEnvName = 'env-${projectName}-${environment}'
var containerAppName = 'ca-${projectName}-${environment}'
var apimName = 'apim-${projectName}-${environment}'
var productId = 'partner-dsr-apis'
var namedValueId = 'backend-internal-secret'

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

resource containerEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      secrets: [
        {
          name: 'partner-api-key'
          value: partnerApiKey
        }
        {
          name: 'backend-internal-secret'
          value: backendInternalSecret
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'dsr-api'
          image: containerImage
          env: [
            {
              name: 'ENVIRONMENT'
              value: 'azure'
            }
            {
              name: 'PARTNER_API_KEY'
              secretRef: 'partner-api-key'
            }
            {
              name: 'REQUIRE_APIM_SECRET'
              value: 'true'
            }
            {
              name: 'BACKEND_INTERNAL_SECRET'
              secretRef: 'backend-internal-secret'
            }
            {
              name: 'OPENAI_MODEL'
              value: 'gpt-5.5'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

resource apim 'Microsoft.ApiManagement/service@2022-08-01' = {
  name: apimName
  location: location
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource product 'Microsoft.ApiManagement/service/products@2022-08-01' = {
  parent: apim
  name: productId
  properties: {
    displayName: 'Partner DSR APIs'
    description: 'Product for partner access to approved DSR APIs.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource namedValue 'Microsoft.ApiManagement/service/namedValues@2022-08-01' = {
  parent: apim
  name: namedValueId
  properties: {
    displayName: 'Backend-Internal-Secret'
    secret: true
    value: backendInternalSecret
  }
}

output acrLoginServer string = acr.properties.loginServer
output containerAppName string = containerApp.name
output apimGatewayUrl string = apim.properties.gatewayUrl
output logAnalyticsWorkspace string = law.name
