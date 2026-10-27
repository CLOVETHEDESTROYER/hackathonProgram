#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { EmberStack } from "../lib/ember-stack";

const app = new cdk.App();

new EmberStack(app, "EmberHackathon", {
  env: {
    account: "242600734479",
    region: "us-west-2",
  },
  description: "Live NASA FIRMS active-fire GeoJSON for a New Mexico bounding box.",
  tags: {
    project: "ember-hackathon",
    event: "ember-to-aftermath",
  },
});
