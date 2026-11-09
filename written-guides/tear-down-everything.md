# Tear Down Everything

Zetaris Hobby is free, but everything you built runs in your own AWS account, and AWS bills for it, even while the cluster is suspended: the control plane, the NAT gateway, the load balancers, the database and the storage. When you're done with the course, delete it all.

**The order matters.** Some resources can only be deleted once others are gone. Follow the steps from top to bottom.

> Make sure the AWS console is set to the region you used for the course (`us-east-1` in the videos).

## 1. Zetaris: terminate the cluster

1. Zetaris Cloud → **Clusters** → your cluster → **Terminate**. Confirm.
2. Wait until the cluster is terminated. This takes a few minutes.
3. **Credentials** → your AWS connection → delete it.

Terminating removes the machines Zetaris started in your account (EKS, load balancers). Zetaris doesn't touch anything else in your AWS account: the rest, you delete yourself.

## 2. AWS: delete the database

1. **Aurora and RDS → Databases** → `northbound-postgres`.
2. Select the instance inside the cluster → **Actions → Delete**. If AWS asks to delete the cluster with it, confirm.
3. **Uncheck** *Create final snapshot* and *Retain automated backups*. Check the acknowledgement, type `delete me`, and click **Delete**.

A final snapshot would keep a copy of the database, and that copy costs storage.

When the database is gone (a few minutes):

4. **EC2 → Security Groups** → `northbound-postgres-sg` → **Actions → Delete security groups**.

If AWS says the group is still in use, the database is still being deleted. Wait a few minutes and try again.

## 3. AWS: delete the Zetaris stack

1. **CloudFormation → Stacks** → the Zetaris stack → **Delete**. Confirm.
2. Wait for `DELETE_COMPLETE`.

The stack removes the network, the NAT gateway with its Elastic IP, and the role Zetaris used.

**If the stack ends in `DELETE_FAILED`:** usually something from the cluster is still in the stack's network.

- Check that the cluster in Zetaris is really terminated, and wait a few minutes.
- **EC2 → Security Groups**: in the stack's VPC, delete leftover groups named `k8s-…` and `eks-cluster-sg-…`. Delete the `k8s-zetarisn-…` groups first, then `k8s-traffic-…` (the others reference it), then `eks-cluster-sg-…`. If a group is still in use, check **EC2 → Load Balancers** and **Network Interfaces** for leftovers.
- Then click **Retry delete** on the stack.

The `default` security groups can't be deleted, and don't need to be: they belong to their VPC and cost nothing.

**About the Elastic IP:** while the NAT gateway uses it, AWS won't let you disassociate it ("You do not have permission"). That's expected. The stack deletes both. If the Elastic IP is still there after the stack is gone, delete the NAT gateway under **VPC → NAT gateways** (if it still exists), wait until it shows *Deleted*, then **EC2 → Elastic IPs → Release Elastic IP address**.

## 4. AWS: delete the buckets

The stack keeps its workspace bucket on purpose, so it can't delete data by accident. Delete it yourself:

1. **S3** → the Zetaris workspace bucket → **Empty**, type `permanently delete`, confirm.
2. **Delete**, type the bucket name, confirm.
3. Do the same for your marketing bucket.

## 5. AWS: delete Zetaris' read-only user

**IAM → Users** → the read-only user from the S3 guide → **Delete**. Type the name and confirm. This deletes its access key too.

## 6. Databricks: remove Zetaris' access

**Settings → Identity and access → Service principals** → the service principal for Zetaris → delete it. That also invalidates its secret.

Databricks Free Edition doesn't cost anything, so the workspace itself can stay. There's no self-service option to delete a Free Edition account. If you want it gone, ask Databricks support.

## 7. Check that nothing is left

- **EC2 → EC2 Global View** shows resources across all regions. Apart from the default VPCs, nothing should be left.
- In your course region, check that these are empty: **EC2 → Instances**, **EC2 → Load Balancers**, **EC2 → Elastic IPs**, **VPC → NAT gateways** (only *Deleted*), **Aurora and RDS → Databases**.

An Elastic IP that isn't attached to anything costs money. Make sure that list is empty.

## 8. Watch your bill for the next few days

AWS reports costs with a delay of up to a day. So check your bill once a day for the next few days:

1. **Billing and Cost Management → Cost Explorer**
2. **Date range:** last 7 days. **Granularity:** Daily. **Group by:** Service.

**What to expect:**

- **Day 1 after the teardown:** the total still goes up. That's normal: the day of the teardown still had costs, and they arrive with a delay.
- **From day 2:** the total should stop climbing. The daily bars should be at or close to zero.

If a service keeps showing costs from day 2 on, its name tells you where to look. *EC2-Other* is usually a leftover Elastic IP, NAT gateway or disk volume.

## Optional: close the AWS account

If you created a separate AWS account just for this course, you can close it once the bill has stopped climbing. For a member account in AWS Organizations: sign in to the **management account** → **AWS Organizations → AWS accounts** → select the account → **Close**. The account stays suspended for 90 days, then it's closed for good.
