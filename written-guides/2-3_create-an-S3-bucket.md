# 2.3 Create an S3 Bucket

For this course, we need a few places to store our data. S3 is one of them. This guide will help you set it up.

Go to the AWS home page. It should look like this:

![AWS home page](/images/aws-home.png)

In the search bar, type in 'S3' and select the S3 recommendation. 

![AWS search for S3](/images/open-s3.png)

> [!IMPORTANT]
> Make sure the region in the top right is US East (N. Virginia) us-east-1, the same as your Zetaris cluster.

You will already see a bucket for Zetaris. But we want to keep our data in a different location. Click on 'Create bucket' to create a new S3 bucket.

![AWS start creating an S3 bucket](/images/create-s3-bucket-init.png)

Next, use these settings:
- **Bucket type:** General purpose
- **Bucket namespace:** Global namespace
- **Bucket name:** E.g. northbound-marketing-<suffix> (set a unique suffix so you don't clash with other buckets).
- **Object Ownership:** ACLs disabled
- **Block Public Access settings for this bucket:** Block all public access
- **Bucket versioning:** Disable
- **Tags:** None
- **Default encryption:**
	- **Encryption type:** Server-side encryption with Amazon S3 managed keys (SSE-S3)
	- **Bucket Key:** Enable
- **Advanced settings - Object Lock:** Disable

Then click 'Create bucket' once again.

![AWS final create bucket button for S3 bucket](/images/create-s3-bucket-final.png)

And with that, your bucket should be successfully created.

![The S3 bucket was created](/images/s3-bucket-created.png)

## Create read-only credentials for Zetaris

Zetaris needs its own credentials to read the files in your bucket. We create a dedicated IAM user that can only read this one bucket and nothing else: least privilege.

In the search bar, type in 'IAM' and select the IAM result.

![AWS search for IAM](/images/open-iam.png)

On the left, select **IAM users**.

![AWS IAM users overview](/images/iam-users.png)

Then click 'Create user'.

![AWS IAM create a new IAM user](/images/create-iam-user.png)

Name the user `zetaris-s3-reader` and click 'Next'. It doesn't need access to the AWS console.

![AWS create IAM user](/images/create-iam-user-name.png)

Select **Attach policies directly**, but don't select any policy. We'll give the user exactly one permission in a moment. Click 'Next'.

![AWS IAM user permissions, no policies selected](/images/create-iam-user-permissions.png)

Click 'Create user'.

![AWS final create user button](/images/create-iam-user-final.png)

Open the newly created user `zetaris-s3-reader`. Click on 'Add permissions' and select 'Create inline policy'.

![AWS add inline policy to IAM user](/images/iam-add-inline-policy.png)

Switch to the **JSON** editor and paste the following policy. Replace `northbound-marketing-<suffix>` with your bucket name in both places. Then click 'Next'.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"],
    "Resource": [
      "arn:aws:s3:::northbound-marketing-<suffix>",
      "arn:aws:s3:::northbound-marketing-<suffix>/*"
    ]
  }]
}
```

![AWS inline policy JSON editor](/images/iam-policy-json.png)

Name the policy `northbound-marketing-read` and click 'Create policy'.

![AWS create inline policy](/images/iam-policy-create.png)

Now we create the access key. Open the **Security credentials** tab, scroll down to **Access keys** and click 'Create access key'.

![AWS IAM security credentials](/images/iam-security-credentials.png)

Select **Third-party service**, confirm the checkbox and click 'Next'. AWS recommends temporary credentials where possible; for this course, a long-lived key that can only read one bucket is fine.

![AWS access key use case](/images/iam-access-key-use-case.png)

Click 'Create access key'.

![AWS create access key](/images/iam-access-key-create.png)

Store both the **Access key** and the **Secret access key** somewhere safe, for example in your password manager, and click 'Done'. You can only see the secret access key once. If you lose it, create a new access key.

![AWS access key created](/images/iam-access-key-done.png)

> **Keep your keys private.** Never commit them to a repository. When you're done with the course, delete the access key or the whole user.