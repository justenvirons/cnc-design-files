## Header ------------------------------------------------------------------  
## Script name: 
## Purpose of script:
## Author: C. Scott Smith, PhD AICP
## Date Created: 2022-08-16
## Date Last Updated: 2022-08-16
## Email: justenvirons@gmail.com
##
## Notes:
##   


# Activate packages -------------------------------------------------------

library(dplyr)
library(tidyverse)
library(elevatr)
library(sf)
library(rayshader)

# https://cran.r-project.org/web/packages/elevatr/vignettes/introduction_to_elevatr.html

# Create variables --------------------------------------------------------

coord_stignace <- data.frame(y = 45.87351090730511, x= -84.695200188661) %>%
  st_as_sf(coords = c("x", "y"), crs=4326)

elev_stignace <- get_elev_raster(coord_stignace, z=4)
mtx_stignace <- raster_to_matrix(elev_stignace)

mtx_stignace %>% sphere_shade(texture = "bw") %>%
  # add_water(detect_water(mtx_stignace,
  #                        zscale = 10), 
  #           color="blue") %>%
  plot_map()



plot_3d(mtx_stignace, 
          zscale = 5,
        zoom )

#
