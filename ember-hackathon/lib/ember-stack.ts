import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as s3deploy from "aws-cdk-lib/aws-s3-deployment";
import { Construct } from "constructs";

const MAP_KEY_PARAMETER = "/ember-hackathon/firms-map-key";
const BBOX = "-109.05,31.33,-103.00,37.00";
const SOURCES = "VIIRS_NOAA21_NRT,VIIRS_NOAA20_NRT,VIIRS_SNPP_NRT,MODIS_NRT";

export class EmberStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    // The MAP_KEY stays outside this stack. A CloudFormation parameter would
    // land in the template and a later deploy would overwrite a CLI update.
    const site = new s3.Bucket(this, "MapSite", {
      bucketName: `ember-hackathon-map-${this.account}`,
      websiteIndexDocument: "index.html",
      websiteErrorDocument: "index.html",
      publicReadAccess: true,
      blockPublicAccess: new s3.BlockPublicAccess({
        blockPublicAcls: true,
        ignorePublicAcls: true,
        blockPublicPolicy: false,
        restrictPublicBuckets: false,
      }),
      encryption: s3.BucketEncryption.S3_MANAGED,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const functionName = "ember-hackathon-fires";
    const logGroup = new logs.LogGroup(this, "FiresLogs", {
      logGroupName: `/aws/lambda/${functionName}`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const fires = new lambda.Function(this, "Fires", {
      functionName,
      description: "NASA FIRMS GeoJSON and a New Mexico property wildfire-prevention assessment.",
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/fires"), {
        exclude: ["test_*.py", "__pycache__", "*.pyc"],
      }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 1024,
      logGroup,
      environment: {
        FIRMS_MAP_KEY_PARAM: MAP_KEY_PARAMETER,
        FIRMS_BBOX: BBOX,
        FIRMS_DAY_RANGE: "2",
        FIRMS_SOURCES: SOURCES,
        SNAPSHOT_BUCKET: site.bucketName,
        SNAPSHOT_KEY: "fires.geojson",
        CACHE_SECONDS: "600",
        BEDROCK_ENABLED: "1",
        BEDROCK_MODEL_ID: "us.anthropic.claude-sonnet-4-6",
        BEDROCK_FALLBACK_MODEL_ID: "us.amazon.nova-lite-v1:0",
        BEDROCK_MAX_TOKENS: "2048",
      },
    });

    fires.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "ReadFirmsMapKey",
        actions: ["ssm:GetParameter"],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/ember-hackathon/firms-map-key`,
        ],
      }),
    );
    fires.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "DecryptFirmsMapKey",
        actions: ["kms:Decrypt"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "kms:ViaService": `ssm.${this.region}.amazonaws.com`,
          },
        },
      }),
    );
    site.grantPut(fires, "fires.geojson");
    // Cross-region profiles need both the profile ARN and each destination
    // foundation-model ARN. Sonnet is primary. Nova Lite is the fallback
    // when Anthropic use-case access is denied.
    fires.addToRolePolicy(
      new iam.PolicyStatement({
        sid: "InvokeEmberVision",
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/us.anthropic.claude-sonnet-4-6`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/us.amazon.nova-lite-v1:0`,
          "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6",
          "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-6",
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-6",
          "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
          "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0",
          "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0",
        ],
      }),
    );

    const firesUrl = new lambda.FunctionUrl(this, "FiresUrl", {
      function: fires,
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ["*"],
        allowedMethods: [lambda.HttpMethod.GET, lambda.HttpMethod.HEAD],
        allowedHeaders: ["*"],
        maxAge: cdk.Duration.hours(1),
      },
    });

    const webDir = path.join(__dirname, "../web");
    const configJs = cdk.Fn.join("", [
      "window.EMBER_CONFIG = {\n",
      '  functionUrl: "',
      firesUrl.url,
      '",\n',
      '  snapshotUrl: "fires.geojson",\n',
      "  bbox: [-109.05, 31.33, -103.0, 37.0],\n",
      '  regionName: "New Mexico",\n',
      "  dayRange: 2,\n",
      '  demo: { name: "Eldorado", lat: 35.520712, lon: -105.937037 }\n',
      "};\n",
    ]);

    new s3deploy.BucketDeployment(this, "SiteFiles", {
      destinationBucket: site,
      sources: [
        s3deploy.Source.asset(webDir, { exclude: ["config.js"] }),
        s3deploy.Source.data("config.js", configJs),
      ],
      cacheControl: [s3deploy.CacheControl.fromString("public, max-age=60")],
      // fires.geojson is written by the Lambda and is not part of this asset.
      prune: false,
    });

    new events.Rule(this, "Refresh", {
      ruleName: "ember-hackathon-refresh",
      description: "Rebuild the New Mexico FIRMS GeoJSON snapshot.",
      schedule: events.Schedule.rate(cdk.Duration.minutes(15)),
      targets: [new targets.LambdaFunction(fires, { retryAttempts: 1 })],
    });

    new cdk.CfnOutput(this, "FunctionUrl", {
      description: "Public HTTPS GeoJSON feed",
      value: firesUrl.url,
    });
    new cdk.CfnOutput(this, "MapUrl", {
      description: "S3 static website (HTTP) with the New Mexico map",
      value: site.bucketWebsiteUrl,
    });
    new cdk.CfnOutput(this, "SnapshotUrl", {
      description: "Cached GeoJSON on the website bucket",
      value: `${site.bucketWebsiteUrl}/fires.geojson`,
    });
    new cdk.CfnOutput(this, "AssessExample", {
      description: "Example property assessment for an Eldorado house",
      value: `${firesUrl.url}assess?lat=35.520712&lon=-105.937037`,
    });
    new cdk.CfnOutput(this, "MapKeyParameter", {
      description: "SSM SecureString the Lambda reads. Not created by this stack.",
      value: MAP_KEY_PARAMETER,
    });
  }
}
