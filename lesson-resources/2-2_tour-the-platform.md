# 2.2 Tour the Platform and Set Auto-Suspend

## Auto-suspend

In your cluster's **Schedule** section, click **Add schedule** and set the days and hours the cluster should run. Outside of the schedule, the cluster is suspended.

Suspending stops the machines, the biggest part of the AWS bill. Load balancer, gateway, control plane and storage keep running until you delete everything (see the [teardown checklist](README.md#when-youre-done-tear-everything-down)).

## Sign in to the cluster

- **Sign-in URL** and **admin credentials:** in the Zetaris Cloud console, under your cluster's **Organisation** section.
- The admin email is the one you entered when creating the cluster.
