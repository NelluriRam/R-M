###### Script name: ekslogin.sh
###### Created by: Satish Kumar
###### Last updated: 21st-Mar-22

#!/usr/bin/bash

USERNAME=AN122589AD
PASSWORD='Qir5UtB6-R5R9t8VD!zw'

#set -x
check_err()
{
if [ $? != 0 ]
then
	echo -e "\n\nThere is some issue with the latest command. Please check.Going to exit now."
	exit 0
fi
}
echo -e "\n\t\t\t====================================== EKS LOGIN UTILITY ======================================\n"

echo -e "Please enter your HA Account username:\c"
#read USERNAME


echo -e "\nPlease paste your HA Account password here:\c"
#read -s PASSWORD


flag=0
while [ $flag -eq 0 ]
do

echo -e "\n\n-----------------AWS ACCOUNTS PROFILES LIST------------------------\n"
cat ~/.aws/config  | grep -w "profile" | cat -n
echo -e "-------------------------------------------------------------------"
echo -e "Please select your profile:\c"
read profile_sn

#set -x
echo "OPTION SELECTED: $profile_sn"
profile_name=`cat ~/.aws/config| grep -w "profile"| awk '{print $2}'| tr -d ']'|awk "NR==$profile_sn"`
#echo "profile_name=$profile_name"

acc_id=`cat ~/.aws/config| grep -C 4 "profile $profile_name" | tail -4| grep "role_arn"| awk -F"::" '{print $2}'| awk -F":" '{print $1}'|tr -d ' '`
echo "AWS_ACCOUNT_ID=$acc_id"

role=`cat ~/.aws/config| grep -C 4 "profile $profile_name" | tail -4| grep "role_arn"| awk -F"/" '{print $2}'| tr -d ' '`
echo -e "role=$role\n"

if [ "$role" == "DeveloperSuperExecutionRole" ]
then
role_name="ADFS-Development-Super"
else
role_name="$role"

case $role in
gld-10xsvc-devrole|gld-pldapi-devrole|gld-psehub-devrole|gld-pspocp-devrole|plat-10xsvc-devrole|plat-pldapi-devrole|plat-psehub-devrole|plat-pspocp-devrole|slvr-10xsvc-devrole|slvr-pldapi-devrole|slvr-psehub-devrole|slvr-pspocp-devrole|SSD-PSEHUB-DevRole|slvr-apm1007420-devrole|gld-apm1007420-devrole|plat-apm1007420-devrole|slvr-workos-devrole|gld-workos-devrole|plat-workos-devrole)
acc_id="738234568511"
echo "AWS account ID is now being updated to:$acc_id"
;;

*) echo "No change in AWS account id. It remains the same as $acc_id"
;;
esac
fi


python ~/.aws/samlapi.py ${USERNAME}@us.ad.wellpoint.com "$PASSWORD" "arn:aws:iam::$acc_id:role/$role_name" "$profile_name" | tail -n 6 | head -5
check_err

while true
do
echo "Region list"
echo "1] us-east-1"
echo "2] us-east-2"
echo "---------------------"
echo -e "Please select the region:\c"
read reg_sn

case $reg_sn in
1)
reg_name="us-east-1"
break;;
2)
reg_name="us-east-2"
break;;
*)
echo "Not a valid input. Please try again."
esac
done

aws eks --region $reg_name --no-verify-ssl list-clusters --profile $profile_name 1>/dev/null
check_err
cl_count=`aws eks --region $reg_name --no-verify-ssl list-clusters --profile $profile_name | sed -n '/\[/,/\]/{/\[/!{/\]/!p}}'| tr -d '  |\"|,|\}|^$'| sed '/^$/d' | wc -l`
check_err


#echo "cl_count=$cl_count"
if [[ $cl_count == 0 ]]
then

echo -e "***  No EKS Cluster found in $reg_name region.Please try some another AWS account or region.  ***\n"
echo -e "Do you want to continue searching for other EKS clusters(y/n):\c"
read ch1

case $ch1 in
y|Y|yes|YES)
flag=0
clear
;;

n|N|no|NO)
flag=1
break
;;

*) echo "Invalid Input. Going to exit now."
exit 0
;;
esac

else

echo -e "\nBelow is the list of EKS cluster in this account:"
aws eks --region $reg_name --no-verify-ssl list-clusters --profile $profile_name | sed -n '/\[/,/\]/{/\[/!{/\]/!p}}'| tr -d '  |\"|,|\}|^$' | cat -n
check_err
echo -e "---------------------------------------------------------"
echo -e "Please select your EKS Cluster:\c"
read cl_sn

cl_name=`aws eks --region $reg_name --no-verify-ssl list-clusters --profile $profile_name| sed -n '/\[/,/\]/{/\[/!{/\]/!p}}'| tr -d '  |\"|,|\}|^$'|awk "NR==$cl_sn"`
#echo -e "cl_name=$cl_name\n\n"
aws eks --region $reg_name --no-verify-ssl update-kubeconfig --name "$cl_name" --profile $profile_name
check_err

#set +x
echo -e "\n\t\t\t***********WELCOME TO $cl_name CLUSTER***********\n"
#kubectl version --client
#check_err
kubectl cluster-info
check_err

flag=1
break

fi

done

#set +x
